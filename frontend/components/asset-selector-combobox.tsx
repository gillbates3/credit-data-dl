"use client";

import { EntitySelectorCombobox } from "@/components/entity-selector-combobox";

interface AssetSelectorComboboxProps {
  initialValue?: string;
}

export function AssetSelectorCombobox({
  initialValue = "",
}: AssetSelectorComboboxProps) {
  return (
    <EntitySelectorCombobox
      initialValue={initialValue}
      mode="asset"
    />
  );
}
