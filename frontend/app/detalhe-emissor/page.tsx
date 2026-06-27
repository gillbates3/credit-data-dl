import { IdentifierSearchForm } from "@/components/identifier-search-form";
import { PageHeader } from "@/components/page-header";

export default function DetalheEmissorPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Detalhe do Emissor"
        title="Selecione um emissor"
        description="Use a busca inteligente abaixo para filtrar por ticker, CNPJ ou emissor."
      />

      <IdentifierSearchForm
        basePath="/detalhe-emissor"
        buttonLabel="Abrir emissor"
      />
    </div>
  );
}
