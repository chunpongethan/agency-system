import { useRef, useEffect } from "react";

/**
 * A small dependency-free rich-text (HTML) editor built on contentEditable +
 * execCommand. Emits HTML via onChange; the server sanitises it on save. Used
 * for training-material remarks.
 */
export default function HtmlEditor({ value, onChange, placeholder }:
  { value: string; onChange: (html: string) => void; placeholder?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  // Load external value in (e.g. when editing a different material) without
  // clobbering the caret while the user is actively typing.
  useEffect(() => {
    const el = ref.current;
    if (el && document.activeElement !== el && el.innerHTML !== (value || "")) {
      el.innerHTML = value || "";
    }
  }, [value]);

  const exec = (cmd: string, arg?: string) => {
    ref.current?.focus();
    document.execCommand(cmd, false, arg);
    onChange(ref.current?.innerHTML ?? "");
  };
  const addLink = () => {
    const url = window.prompt("URL (https://…)");
    if (url) exec("createLink", url);
  };
  const insertImageUrl = () => {
    const url = window.prompt("Image URL (https://…)");
    if (url) exec("insertHTML", `<img src="${url.replace(/"/g, "")}" alt="" />`);
  };
  // Paste an image straight from the clipboard (e.g. a screenshot) — embed it as
  // a data URL. Other paste content falls through to the default handler and is
  // sanitised server-side on save.
  const onPaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (!file) continue;
        e.preventDefault();
        const reader = new FileReader();
        reader.onload = () => exec("insertHTML", `<img src="${reader.result}" alt="" />`);
        reader.readAsDataURL(file);
        return;
      }
    }
  };
  const Btn = ({ on, title, children }: { on: () => void; title: string; children: React.ReactNode }) => (
    <button type="button" className="he-btn" title={title}
      onMouseDown={(e) => e.preventDefault()} onClick={on}>{children}</button>
  );

  return (
    <div className="html-editor">
      <div className="he-toolbar">
        <Btn on={() => exec("bold")} title="Bold"><b>B</b></Btn>
        <Btn on={() => exec("italic")} title="Italic"><i>I</i></Btn>
        <Btn on={() => exec("underline")} title="Underline"><u>U</u></Btn>
        <span className="he-sep" />
        <Btn on={() => exec("insertUnorderedList")} title="Bulleted list">• —</Btn>
        <Btn on={() => exec("insertOrderedList")} title="Numbered list">1.</Btn>
        <Btn on={addLink} title="Link">🔗</Btn>
        <Btn on={insertImageUrl} title="Insert image by URL">🖼</Btn>
        <span className="he-sep" />
        <Btn on={() => exec("removeFormat")} title="Clear formatting">✕</Btn>
      </div>
      <div ref={ref} className="he-content" contentEditable suppressContentEditableWarning
        data-placeholder={placeholder ?? ""}
        onPaste={onPaste}
        onInput={() => onChange(ref.current?.innerHTML ?? "")} />
    </div>
  );
}
