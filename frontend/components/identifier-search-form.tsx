"use client";

import { EntitySelectorCombobox } from "@/components/entity-selector-combobox";

interface IdentifierSearchFormProps {
  basePath: string;
  buttonLabel: string;
  queryParam?: string;
  placeholder?: string;
}

export function IdentifierSearchForm({
  basePath,
  buttonLabel,
  queryParam,
  placeholder,
}: IdentifierSearchFormProps) {
  void basePath;
  void buttonLabel;
  void queryParam;
  void placeholder;

  return <EntitySelectorCombobox mode="issuer" />;
}
