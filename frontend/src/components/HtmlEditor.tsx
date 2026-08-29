import { useRef, useEffect } from "react";

// Pasted images are embedded inline as data URLs, so a raw phone photo would
// bloat the saved remark to several MB and can be dropped by the reverse proxy
// (surfacing as "Failed to fetch" on save). Downscale + re-encode to keep the
// embedded image small; a remark never needs full-resolution.
const MAX_IMG_DIM = 1600;
const IMG_QUALITY = 0.82;

// Downscale `file` to at most MAX_IMG_DIM on its long edge and re-encode as a
// compact JPEG data URL. Resolves to the original data URL if anything about
// the canvas path fails, so pasting still works in a degraded browser.
function compressImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const original = reader.result as string;
      const img = new Image();
      img.onerror = () => resolve(original);
      img.onload = () => {
        try {
          const scale = Math.min(1, MAX_IMG_DIM / Math.max(img.width, img.height));
          const w = Math.max(1, Math.round(img.width * scale));
          const h = Math.max(1, Math.round(img.height * scale));
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          if (!ctx) return resolve(original);
          ctx.drawImage(img, 0, 0, w, h);
          const out = canvas.toDataURL("image/jpeg", IMG_QUALITY);
          // Keep whichever is smaller (tiny PNGs can beat JPEG).
          resolve(out.length < original.length ? out : original);
        } catch {
          resolve(original);
        }
      };
      img.src = original;
    };
    reader.readAsDataURL(file);
  });
}

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
  // Paste an image straight from the clipboard (e.g. a screenshot) — downscale
  // it and embed as a compact data URL (a full-res paste would bloat the saved
  // remark and get rejected by the proxy). Other paste content falls through to
  // the default handler and is sanitised server-side on save.
  const onPaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (!file) continue;
        e.preventDefault();
        compressImage(file)
          .then((src) => exec("insertHTML", `<img src="${src}" alt="" />`))
          .catch(() => { /* ignore a failed paste */ });
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
