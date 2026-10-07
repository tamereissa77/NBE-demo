import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Markdown with citation markers [S1] turned into clickable chips.
export function Md({ text, onCite, className = "" }: { text: string; onCite?: (label: string) => void; className?: string }) {
  const withChips = onCite ? text.replace(/\[(S\d+)\]/g, "[$1](#cite-$1)") : text;
  return (
    <div dir="auto" className={`nbe-md text-sm leading-relaxed text-nbe-strong ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) =>
            href?.startsWith("#cite-") ? (
              <button
                onClick={() => onCite?.(href.slice(6))}
                className="mx-0.5 inline-flex items-center rounded-md bg-nbe-orange/20 px-1.5 text-xs font-bold text-nbe-green-dark hover:bg-nbe-orange/40"
              >
                {children}
              </button>
            ) : (
              <a href={href} className="text-nbe-green underline">
                {children}
              </a>
            ),
        }}
      >
        {withChips}
      </ReactMarkdown>
    </div>
  );
}
