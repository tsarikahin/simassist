import { useId, useRef, useState, type CSSProperties } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";

interface SelectionPickerProps {
  options: { value: string; label: string }[];
  value: string;
  label: string;
  heading: string;
  placeholder: string;
  disabled?: boolean;
  placement?: "top" | "bottom";
  onSelect: (value: string) => void;
  action?: { label: string; onClick: () => void };
}

export function SelectionPicker({ options, value, label, heading, placeholder, disabled = false, placement = "bottom", onSelect, action }: SelectionPickerProps) {
  const id = useId();
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  function closeMenu() {
    menu.current?.hidePopover();
    trigger.current?.focus();
  }

  return <div className="selection-picker" style={{ "--picker-anchor": `--picker-${id.replace(/[^a-zA-Z0-9_-]/g, "")}` } as CSSProperties}>
    <button ref={trigger} className="selection-picker-trigger" type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} aria-controls={id} popoverTarget={id} disabled={disabled}
      onKeyDown={event => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          menu.current?.showPopover();
        }
      }}>
      <span>{options.find(option => option.value === value)?.label ?? placeholder}</span><ChevronDown size={16} aria-hidden="true" />
    </button>
    <div ref={menu} id={id} className="selection-picker-menu" popover="auto" role="menu" aria-label={heading} data-placement={placement}
      onToggle={event => {
        const isOpen = event.newState === "open";
        setOpen(isOpen);
        if (isOpen) {
          const selected = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]');
          (selected ?? menu.current?.querySelector<HTMLButtonElement>("button"))?.focus();
        }
      }}
      onKeyDown={event => {
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const step = event.key === "ArrowDown" ? 1 : -1;
          buttons[(index + step + buttons.length) % buttons.length]?.focus();
        }
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          (event.key === "Home" ? buttons[0] : buttons.at(-1))?.focus();
        }
      }}>
      <div className="selection-picker-menu-heading">{heading}</div>
      <div className="selection-picker-options" role="group" aria-label={heading}>
        {options.map(option => <button key={option.value} type="button" role="menuitemradio" aria-checked={option.value === value}
          onClick={() => { onSelect(option.value); closeMenu(); }}>
          <span>{option.label}</span>{option.value === value && <Check size={17} aria-hidden="true" />}
        </button>)}
      </div>
      {action && <>
        <div className="selection-picker-menu-divider" role="separator" />
        <button className="selection-picker-menu-add" type="button" role="menuitem" onClick={() => { closeMenu(); action.onClick(); }}>
          <Plus size={17} aria-hidden="true" /><span>{action.label}</span>
        </button>
      </>}
    </div>
  </div>;
}
