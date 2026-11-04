/** 路由切换时做一次 View Transition，让搜索框从首页位置移到结果页位置。 */

let running = false

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function nextTask() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

/** 这一次换页已经交给 View Transition，页面就别再叠一层入场动画。 */
export function viewTransitionRunning() {
  return running
}

export function navigateWithTransition(navigate, to) {
  if (typeof document === 'undefined' || !document.startViewTransition || prefersReducedMotion()) {
    navigate(to)
    return
  }

  running = true
  const transition = document.startViewTransition(async () => {
    navigate(to)
    // 路由状态在 React 的批处理里提交，等两个宏任务让新页面落到 DOM 再快照
    await nextTask()
    await nextTask()
  })

  transition.finished.finally(() => {
    running = false
  })
}
