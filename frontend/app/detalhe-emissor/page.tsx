import { IdentifierSearchForm } from "@/components/identifier-search-form";
import { PageHeader } from "@/components/page-header";

export default function DetalheEmissorPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Detalhe do Emissor"
        title="Visão completa do emissor"
        description="Busque por CNPJ, ticker ou nome do emissor para abrir a visão consolidada com debêntures vinculadas, dados financeiros, manifestos quantitativos e markdowns qualitativos."
      />

      <IdentifierSearchForm
        basePath="/detalhe-emissor"
        buttonLabel="Abrir emissor"
      />
    </div>
  );
}
