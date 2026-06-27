"""
Orquestrador V2 do pipeline de cadastro.

Contrato importante: este modulo NAO cria processos. A camada de API deve criar o
registro em `pipeline_jobs`, devolver o `process_id` ao front e depois disparar
`ingerir_ticker(...)` ou `ingerir_documentos(...)` com esse `process_id`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts_v2 import servico_repositorio as repo
    from scripts_v2.servico_cvm import buscar_dados_cvm
    from scripts_v2.servico_ia_qualitativa import (
        extrair_markdown_pdf,
        gerar_titulo_documento,
    )
    from scripts_v2.servico_ia_quantitativa import (
        carregar_arquivos_em_memoria,
        extrair_dados_quantitativos,
    )
    from scripts_v2.servico_identidade import buscar_identidade_emissor
    from scripts_v2.servico_mercado import buscar_dados_mercado
except ImportError:
    import servico_repositorio as repo
    from servico_cvm import buscar_dados_cvm
    from servico_ia_qualitativa import extrair_markdown_pdf, gerar_titulo_documento
    from servico_ia_quantitativa import (
        carregar_arquivos_em_memoria,
        extrair_dados_quantitativos,
    )
    from servico_identidade import buscar_identidade_emissor
    from servico_mercado import buscar_dados_mercado


def _md5(conteudo: bytes) -> str:
    return hashlib.md5(conteudo).hexdigest()


async def _to_thread(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)


def _append_erro(progresso: dict[str, Any], mensagem: str) -> None:
    progresso.setdefault("erros", []).append(mensagem)


def _append_passo(progresso: dict[str, Any], passo: str) -> None:
    passos = progresso.setdefault("passos_concluidos", [])
    if passo not in passos:
        passos.append(passo)


def _formatar_excecao(exc: Exception) -> str:
    detalhe = str(exc).strip()
    if detalhe:
        return f"{type(exc).__name__}: {detalhe}"
    return f"{type(exc).__name__}: {exc!r}"


def _append_mensagem_andamento(progresso: dict[str, Any], mensagem: str) -> None:
    texto = " ".join(str(mensagem or "").split()).strip()
    if not texto:
        return

    horario = time.strftime("%H:%M:%S")
    mensagens = progresso.setdefault("mensagens_andamento", [])
    if isinstance(mensagens, list):
        mensagens.append(f"[{horario}] {texto}")


def _criar_notificador_andamento(
    process_id: str | None,
    progresso: dict[str, Any],
    *,
    etapa_atual: str,
) -> Callable[[str], None]:
    def notificar(mensagem: str) -> None:
        _append_mensagem_andamento(progresso, mensagem)
        if not process_id:
            return

        try:
            repo.atualizar_processo(
                process_id,
                status="rodando",
                etapa_atual=etapa_atual,
                progresso=dict(progresso),
            )
        except Exception:
            pass

    return notificar


async def _atualizar_processo(
    process_id: str | None,
    progresso: dict[str, Any],
    *,
    status: str | None = None,
    etapa_atual: str | None = None,
    erro: str | None = None,
) -> None:
    if not process_id:
        return
    await _to_thread(
        repo.atualizar_processo,
        process_id,
        status=status,
        etapa_atual=etapa_atual,
        progresso=dict(progresso),
        erro=erro,
    )


async def ingerir_ticker(
    ticker: str,
    *,
    deep: bool = False,
    data_corte_deep: str | None = None,
    process_id: str | None = None,
) -> dict[str, Any]:
    ticker_norm = (ticker or "").strip().upper()
    progresso: dict[str, Any] = {
        "passos_concluidos": [],
        "periodos_cvm": 0,
        "eventos_agenda": 0,
        "dias_historico": 0,
        "mensagens_andamento": [],
        "erros": [],
    }
    try:
        notificar_identidade = _criar_notificador_andamento(
            process_id,
            progresso,
            etapa_atual="identidade",
        )
        notificar_cvm = _criar_notificador_andamento(
            process_id,
            progresso,
            etapa_atual="cvm",
        )
        notificar_mercado = _criar_notificador_andamento(
            process_id,
            progresso,
            etapa_atual="mercado",
        )
        _append_mensagem_andamento(
            progresso,
            f"Iniciando cadastro do ticker {ticker_norm}.",
        )
        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="identidade",
        )
        identidade = await buscar_identidade_emissor(
            ticker_norm,
            status_callback=notificar_identidade,
        )
        if identidade.get("status") != "SUCESSO":
            mensagem = (
                f"Falha ao resolver identidade para {ticker_norm}: "
                f"status={identidade.get('status')}"
            )
            _append_erro(progresso, mensagem)
            await _atualizar_processo(
                process_id,
                progresso,
                status="erro",
                etapa_atual="identidade",
                erro=mensagem,
            )
            return {
                "ticker": ticker_norm,
                "cnpj": identidade.get("cnpj_emissor"),
                "tipo_capital": identidade.get("tipo_capital"),
                "periodos_cvm": 0,
                "eventos_agenda": 0,
                "dias_historico": 0,
                "erros": progresso["erros"],
            }

        cnpj = str(identidade.get("cnpj_emissor") or "")
        cod_cvm = identidade.get("cod_cvm")
        tipo_capital = identidade.get("tipo_capital")

        await _to_thread(repo.salvar_emissor, identidade)
        _append_passo(progresso, "identidade")
        progresso["cnpj"] = cnpj
        progresso["nome_emissor"] = identidade.get("nome_emissor")
        progresso["tipo_capital"] = tipo_capital
        _append_mensagem_andamento(
            progresso,
            f"Emissor identificado: {identidade.get('nome_emissor') or ticker_norm} ({cnpj or 'sem CNPJ'}).",
        )
        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="identidade",
        )

        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="cvm",
        )
        if cod_cvm:
            try:
                notificar_cvm(
                    f"Iniciando coleta de demonstracoes na CVM para o codigo {cod_cvm}."
                )
                resultado_cvm = await buscar_dados_cvm(
                    cnpj,
                    str(cod_cvm),
                    status_callback=notificar_cvm,
                )
                linhas = await _to_thread(repo.periodos_para_linhas, cnpj, resultado_cvm)
                await _to_thread(repo.salvar_demonstracoes, linhas)
                progresso["periodos_cvm"] = len((resultado_cvm or {}).get("periodos") or {})
                _append_passo(progresso, "cvm")
                _append_mensagem_andamento(
                    progresso,
                    f"Etapa CVM concluida com {progresso['periodos_cvm']} periodos encontrados.",
                )
            except Exception as exc:
                _append_erro(progresso, f"Falha nao fatal em CVM para {ticker_norm}: {exc}")
        else:
            progresso["cvm_pulado"] = (
                "Emissor sem codigo CVM; demonstracoes virao apenas por PDFs."
            )
            _append_passo(progresso, "cvm_pulado")
            _append_mensagem_andamento(
                progresso,
                "Etapa CVM pulada porque o emissor nao possui codigo CVM.",
            )
        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="cvm",
        )

        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="mercado",
        )
        try:
            notificar_mercado(
                "Iniciando coleta de caracteristicas, agenda e historico de mercado."
            )
            resultado_mkt = await buscar_dados_mercado(
                ticker_norm,
                deep=deep,
                data_corte_deep=data_corte_deep,
                datas_desconhecidas=None,
                status_callback=notificar_mercado,
            )
            caracteristicas = (resultado_mkt or {}).get("caracteristicas") or {}
            agenda = (resultado_mkt or {}).get("agenda") or []
            historico = (resultado_mkt or {}).get("historico_diario") or []

            await _to_thread(repo.salvar_caracteristicas, cnpj, ticker_norm, caracteristicas)
            await _to_thread(repo.salvar_agenda, cnpj, ticker_norm, agenda)
            await _to_thread(repo.salvar_historico, ticker_norm, historico)

            progresso["eventos_agenda"] = len(agenda)
            progresso["dias_historico"] = len(historico)
            _append_passo(progresso, "mercado")
            _append_mensagem_andamento(
                progresso,
                f"Etapa mercado concluida com {len(agenda)} eventos e {len(historico)} dias de historico.",
            )
        except Exception as exc:
            _append_erro(progresso, f"Falha nao fatal em mercado para {ticker_norm}: {exc}")

        status_final = "concluido_com_erros" if progresso["erros"] else "concluido"
        _append_passo(progresso, "finalizado")
        _append_mensagem_andamento(
            progresso,
            f"Cadastro do ticker {ticker_norm} concluido.",
        )
        await _atualizar_processo(
            process_id,
            progresso,
            status=status_final,
            etapa_atual="mercado",
        )
        return {
            "ticker": ticker_norm,
            "cnpj": cnpj,
            "tipo_capital": tipo_capital,
            "periodos_cvm": progresso["periodos_cvm"],
            "eventos_agenda": progresso["eventos_agenda"],
            "dias_historico": progresso["dias_historico"],
            "erros": progresso["erros"],
        }
    except Exception as exc:
        mensagem = (
            f"Falha inesperada em ingerir_ticker({ticker_norm}): "
            f"{_formatar_excecao(exc)}"
        )
        _append_erro(progresso, mensagem)
        await _atualizar_processo(
            process_id,
            progresso,
            status="erro",
            erro=mensagem,
        )
        raise


async def ingerir_documentos(
    cnpj: str,
    arquivos: list[tuple[str, bytes]],
    *,
    force: bool = False,
    process_id: str | None = None,
) -> dict[str, Any]:
    cnpj_norm = repo.normaliza_cnpj(cnpj)
    progresso: dict[str, Any] = {
        "passos_concluidos": [],
        "quant_processados": 0,
        "qual_processados": 0,
        "qual_fallback": 0,
        "qual_sem_conteudo": 0,
        "pulados_quant": 0,
        "pulados_qual": 0,
        "mensagens_andamento": [],
        "erros": [],
    }
    try:
        emissor = await _to_thread(repo.buscar_emissor, cnpj_norm)
        if emissor is None:
            mensagem = "emissor inexistente; rode ingerir_ticker primeiro"
            _append_erro(progresso, mensagem)
            await _atualizar_processo(
                process_id,
                progresso,
                status="erro",
                etapa_atual="validacao_emissor",
                erro=mensagem,
            )
            return {
                "cnpj": cnpj_norm,
                "quant_processados": 0,
                "qual_processados": 0,
                "qual_fallback": 0,
                "qual_sem_conteudo": 0,
                "pulados_quant": 0,
                "pulados_qual": 0,
                "erros": progresso["erros"],
            }

        progresso["cnpj"] = cnpj_norm
        progresso["nome_emissor"] = emissor.get("nome")
        _append_passo(progresso, "validacao_emissor")
        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="peek_hashes",
        )
        hashes_quant = await _to_thread(repo.buscar_hashes_quantitativo, cnpj_norm)
        hashes_qual = await _to_thread(repo.buscar_hashes_qualitativo, cnpj_norm)

        novos_quant = [
            (nome, conteudo)
            for nome, conteudo in arquivos
            if force or _md5(conteudo) not in hashes_quant
        ]
        novos_qual = [
            (nome, conteudo)
            for nome, conteudo in arquivos
            if force or _md5(conteudo) not in hashes_qual
        ]

        progresso["pulados_quant"] = len(arquivos) - len(novos_quant)
        progresso["pulados_qual"] = len(arquivos) - len(novos_qual)
        _append_mensagem_andamento(
            progresso,
            "Check de duplicidade concluído. Preparando os próximos passos.",
        )
        _append_passo(progresso, "peek_hashes")
        await _atualizar_processo(
            process_id,
            progresso,
            status="rodando",
            etapa_atual="peek_hashes",
        )

        if novos_quant:
            notificar_quant = _criar_notificador_andamento(
                process_id,
                progresso,
                etapa_atual="ia_quant",
            )
            await _atualizar_processo(
                process_id,
                progresso,
                status="rodando",
                etapa_atual="ia_quant",
            )
            try:
                periodos_db = sorted(
                    await _to_thread(repo.buscar_periodos_demonstracoes, cnpj_norm)
                )
                resultado_q = await _to_thread(
                    extrair_dados_quantitativos,
                    cnpj_norm,
                    novos_quant,
                    periodos_db,
                    status_callback=notificar_quant,
                )
                linhas = await _to_thread(repo.periodos_para_linhas, cnpj_norm, resultado_q)
                await _to_thread(repo.salvar_demonstracoes, linhas)

                processed_files = (resultado_q or {}).get("processed_files") or []
                for arquivo_processado in processed_files:
                    await _to_thread(
                        repo.salvar_compendio_quantitativo,
                        cnpj_norm,
                        arquivo_processado["nome_arquivo"],
                        arquivo_processado["hash_md5"],
                        force,
                    )

                progresso["quant_processados"] = len(processed_files)
                progresso["pulados_quant"] += max(
                    0, len(novos_quant) - len(processed_files)
                )
            except Exception as exc:
                progresso["pulados_quant"] += len(novos_quant)
                _append_erro(
                    progresso,
                    f"Falha durante o processamento quantitativo de {cnpj_norm}: {exc}",
                )
            _append_passo(progresso, "ia_quant")
        else:
            _append_passo(progresso, "ia_quant")

        if novos_qual:
            notificar_qual = _criar_notificador_andamento(
                process_id,
                progresso,
                etapa_atual="ia_qual",
            )
            await _atualizar_processo(
                process_id,
                progresso,
                status="rodando",
                etapa_atual="ia_qual",
            )
            for nome, conteudo in novos_qual:
                md5_arquivo = _md5(conteudo)
                try:
                    markdown, modo = await _to_thread(
                        extrair_markdown_pdf,
                        cnpj_norm,
                        nome,
                        conteudo,
                        status_callback=notificar_qual,
                    )
                    if modo == "placeholder":
                        titulo = Path(nome).stem or nome
                    else:
                        titulo = await _to_thread(
                            gerar_titulo_documento,
                            cnpj_norm,
                            nome,
                            markdown,
                        )
                    await _to_thread(
                        repo.salvar_compendio_qualitativo,
                        cnpj_norm,
                        nome,
                        md5_arquivo,
                        markdown,
                        force,
                        titulo,
                    )
                    await _to_thread(
                        repo.definir_titulo_quantitativo,
                        cnpj_norm,
                        md5_arquivo,
                        titulo,
                    )
                    progresso["qual_processados"] += 1
                    if modo == "texto_bruto":
                        progresso["qual_fallback"] += 1
                        _append_erro(
                            progresso,
                            f"Markdown via texto bruto (LLM nao retornou estruturado) para {nome}.",
                        )
                    elif modo == "placeholder":
                        progresso["qual_sem_conteudo"] += 1
                        _append_erro(
                            progresso,
                            f"PDF sem texto extraivel; salvo placeholder para {nome}.",
                        )
                except Exception as exc:
                    progresso["pulados_qual"] += 1
                    _append_erro(
                        progresso,
                        f"Falha no qualitativo para o arquivo {nome}: {exc}",
                    )
                await _atualizar_processo(
                    process_id,
                    progresso,
                    status="rodando",
                    etapa_atual="ia_qual",
                )
            _append_passo(progresso, "ia_qual")
        else:
            _append_passo(progresso, "ia_qual")

        status_final = "concluido_com_erros" if progresso["erros"] else "concluido"
        _append_passo(progresso, "finalizado")
        _append_mensagem_andamento(progresso, "Processamento concluído.")
        await _atualizar_processo(
            process_id,
            progresso,
            status=status_final,
            etapa_atual="finalizado",
        )
        return {
            "cnpj": cnpj_norm,
            "quant_processados": progresso["quant_processados"],
            "qual_processados": progresso["qual_processados"],
            "qual_fallback": progresso["qual_fallback"],
            "qual_sem_conteudo": progresso["qual_sem_conteudo"],
            "pulados_quant": progresso["pulados_quant"],
            "pulados_qual": progresso["pulados_qual"],
            "erros": progresso["erros"],
        }
    except Exception as exc:
        mensagem = (
            f"Falha inesperada em ingerir_documentos({cnpj_norm}): "
            f"{_formatar_excecao(exc)}"
        )
        _append_erro(progresso, mensagem)
        await _atualizar_processo(
            process_id,
            progresso,
            status="erro",
            erro=mensagem,
        )
        raise


async def _executar_cli(args: argparse.Namespace) -> dict[str, Any]:
    if args.comando == "ticker":
        return await ingerir_ticker(
            args.ticker,
            deep=args.deep,
            data_corte_deep=args.data_corte_deep,
            process_id=args.process_id,
        )

    if args.comando == "docs":
        pasta_pdfs = Path(args.pasta_pdfs)
        if not pasta_pdfs.exists():
            raise SystemExit(f"Pasta nao encontrada: {pasta_pdfs}")
        arquivos = carregar_arquivos_em_memoria(pasta_pdfs)
        if not arquivos:
            raise SystemExit(f"Nenhum PDF encontrado em: {pasta_pdfs}")
        return await ingerir_documentos(
            args.cnpj,
            arquivos,
            force=args.force,
            process_id=args.process_id,
        )

    raise SystemExit("Comando invalido. Use 'ticker' ou 'docs'.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orquestrador V2 do pipeline de cadastro")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    parser_ticker = subparsers.add_parser("ticker", help="Ingere identidade, CVM e mercado")
    parser_ticker.add_argument("ticker", help="Ticker da debenture (ex: PETR26)")
    parser_ticker.add_argument(
        "--deep",
        action="store_true",
        help="Ativa a camada deep do servico de mercado",
    )
    parser_ticker.add_argument(
        "--data-corte-deep",
        default=None,
        help="Data minima YYYY-MM-DD para preencher taxas na camada deep",
    )
    parser_ticker.add_argument(
        "--process-id",
        default=None,
        help="Processo existente em pipeline_jobs a ser atualizado",
    )

    parser_docs = subparsers.add_parser(
        "docs",
        help="Ingere PDFs de upload nas trilhas quantitativa e qualitativa",
    )
    parser_docs.add_argument("cnpj", help="CNPJ do emissor")
    parser_docs.add_argument("pasta_pdfs", help="Pasta contendo PDFs")
    parser_docs.add_argument(
        "--force",
        action="store_true",
        help="Ignora o pre-filtro por hash e reprocessa os PDFs",
    )
    parser_docs.add_argument(
        "--process-id",
        default=None,
        help="Processo existente em pipeline_jobs a ser atualizado",
    )

    return parser


if __name__ == "__main__":
    resultado = asyncio.run(_executar_cli(_build_parser().parse_args()))
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
