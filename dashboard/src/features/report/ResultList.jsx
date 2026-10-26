import ResultItem from './ResultItem.jsx'

export default function ResultList({ hits, startIndex = 0, selectedId, onSelect, terms = [] }) {
  return (
    <ul className="results">
      {hits.map((hit, index) => (
        <ResultItem
          key={hit.report_id}
          hit={hit}
          index={index}
          startIndex={startIndex}
          selected={hit.report_id === selectedId}
          onSelect={onSelect}
          terms={terms}
        />
      ))}
    </ul>
  )
}
