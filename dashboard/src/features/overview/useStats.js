import { useCallback, useEffect, useState } from 'react'

const INITIAL = { data: null, loading: true, error: '' }

export function useStats(loader) {
  const [state, setState] = useState(INITIAL)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let alive = true

    loader()
      .then((data) => {
        if (alive) setState({ data, loading: false, error: '' })
      })
      .catch((err) => {
        if (!alive) return
        setState({
          data: null,
          loading: false,
          error: err.message || '统计读取失败',
        })
      })

    return () => {
      alive = false
    }
  }, [loader, reloadKey])

  const reload = useCallback(() => {
    setState({ data: null, loading: true, error: '' })
    setReloadKey((value) => value + 1)
  }, [])

  return { ...state, reload }
}
