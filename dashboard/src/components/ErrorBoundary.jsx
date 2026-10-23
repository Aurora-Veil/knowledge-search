import { Component } from 'react'

// 渲染阶段抛异常时，React 会把整棵树卸载掉，页面上什么都不剩，
// 也就是俗称的“白屏”。这个组件接住异常，把错误显示出来。
//
// 它只能接住 render 期间抛的错：比 setState 回调、事件处理函数、
// setTimeout、await 之后的异常都要自己 try/catch，边界接不到。
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // 控制台里保留完整堆栈，页面上的短文案只是给眼睛一个落点
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
