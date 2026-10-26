import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('页面渲染出错：', error, info?.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="crash">
        <h1 className="crash-title">页面渲染出错了</h1>
        <p className="crash-note">
          多半是某个组件拿到了 undefined 或者导入路径写错。控制台里有完整堆栈。
        </p>
        <pre className="crash-detail">{String(error.message || error)}</pre>
        <button className="btn btn-primary" type="button" onClick={() => window.location.reload()}>
          重新加载
        </button>
      </div>
    )
  }
}
