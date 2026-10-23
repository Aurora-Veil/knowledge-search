import { highlightSegments } from "./highlight.js";

export default function HighlightText({ html }) {
  return highlightSegments(html).map((segment, index) =>
    segment.hit ? (
      <mark className="hl" key={index}>
        {segment.text}
      </mark>
    ) : (
      <span key={index}>{segment.text}</span>
    ),
  );
}
