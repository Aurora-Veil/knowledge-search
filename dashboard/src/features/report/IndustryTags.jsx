import { useState } from "react";
import { countIndustries } from "./industry.js";

const VISIBLE_LIMIT = 6;

export default function IndustryTags({ hits }) {
  const [expanded, setExpanded] = useState(false);

  const tags = countIndustries(hits);
  if (!tags.length) return null;

  const shown = expanded ? tags : tags.slice(0, VISIBLE_LIMIT);
  const hidden = tags.length - shown.length;

  return (
    <section className="industry">
      <div className="industry-head">
        <span>本页行业分布</span>
        <span className="industry-note">
          {hits.length} 条结果 · {tags.length} 个标签
        </span>
      </div>

      <ul className={expanded ? "industry-tags is-expanded" : "industry-tags"}>
        {shown.map((tag) => (
          <li className="industry-tag" key={tag.name}>
            <span className="industry-tag-name" title={tag.name}>
              {tag.name}
            </span>
            <span className="industry-tag-count">{tag.count}</span>
          </li>
        ))}

        {tags.length > VISIBLE_LIMIT && (
          <li>
            <button
              className="industry-tag industry-more"
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "收起" : `展开其余 ${hidden} 个`}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
