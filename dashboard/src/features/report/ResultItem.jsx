import { formatScore } from "./format.js";
import HighlightText from "./HighlightText.jsx";
import { matchesTerm } from "./highlight.js";

export default function ResultItem({ hit, index, startIndex = 0, selected, onSelect, terms = [] }) {
  function select() {
    onSelect(hit.report_id);
  }

  return (
    <li
      className={selected ? "result is-selected" : "result"}
      role="button"
      tabIndex={0}
      aria-current={selected ? "true" : undefined}
      onClick={select}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      }}
    >
      <div className="result-top">
        <span className="result-idx">{startIndex + index + 1}</span>
        <span className="result-title">
          <HighlightText html={hit.highlight?.title?.[0] ?? hit.title} />
        </span>
      </div>

      {hit.highlight?.summary?.[0] && (
        <p className="result-snippet">
          <HighlightText html={hit.highlight.summary[0]} />
        </p>
      )}

      <div className="result-meta">
        {hit.industry.slice(0, 2).map((name) => (
          <span className={matchesTerm(name, terms) ? "chip chip-hit" : "chip"} key={name}>
            {name}
          </span>
        ))}
        <span>{hit.layout}</span>
        <span>{hit.publish_date}</span>
        <span className="result-score">{formatScore(hit.score)}</span>
      </div>
    </li>
  );
}
