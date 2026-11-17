import { SelectionPicker } from "../../../components/SelectionPicker";

interface ModelPickerProps {
  models: string[];
  selectedModel: string;
  disabled: boolean;
  onSelect: (model: string) => void;
  onAdd: () => void;
}

export function ModelPicker({ models, selectedModel, disabled, onSelect, onAdd }: ModelPickerProps) {
  return <div className="chat-model-menu-picker">
    <span>Model</span>
    <SelectionPicker
      options={models.map(model => ({ value: model, label: model }))}
      value={selectedModel}
      label="Chat model"
      heading="Available models"
      placeholder="Select model"
      disabled={disabled}
      placement="top"
      onSelect={onSelect}
      action={{ label: "Add model…", onClick: onAdd }}
    />
  </div>;
}
