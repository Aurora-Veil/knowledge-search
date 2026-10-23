import ResultItem from './ResultItem.jsx'

export default function ResultList({ hits, selectedId, onSelect, terms = [] }) {
  return (
    <ul className="results">
      {hits.map((hit, index) => (
        <ResultItem
          key={hit.report_id}
          hit={hit}
          index={index}
          selected={hit.report_id === selectedId}
          onSelect={onSelect}
          terms={terms}
        />
      ))}
    </ul>
  )
}
