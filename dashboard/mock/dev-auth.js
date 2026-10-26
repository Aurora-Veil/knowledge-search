const users = new Map([
  ['demo', { id: 1, username: 'demo', password: 'demo1234', is_active: true }],
  [
    'disabled',
    { id: 2, username: 'disabled', password: 'disabled1234', is_active: false },
  ],
])

const tokens = new Map()
let nextId = 3

const USERNAME_RE = /^[A-Za-z0-9_-]{3,32}$/

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
  })
}

function publicUser(user) {
  return {
    id: user.id,
    username: user.username,
    is_active: user.is_active,
    created_at: new Date().toISOString(),
  }
}

function tokenOf(req) {
  const header = req.headers.authorization || ''
  return header.startsWith('Bearer ') ? header.slice(7) : ''
}

export function tokenUser(req) {
  return tokens.get(tokenOf(req)) || null
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function handle(req, res, pathname) {
  await delay(300)

  const method = req.method

  if (method === 'POST' && pathname === '/api/v1/auth/token') {
    const form = new URLSearchParams(await readBody(req))
    const username = (form.get('username') || '').trim()
    const password = form.get('password') || ''
    const user = users.get(username.toLowerCase())

    if (!user || user.password !== password) {
      return send(res, 401, { detail: 'Incorrect username or password' })
    }
    if (!user.is_active) {
      return send(res, 403, { detail: 'Inactive user' })
    }

    const token = `mock-${user.id}-${Math.random().toString(36).slice(2)}`
    tokens.set(token, user)
    return send(res, 200, { access_token: token, token_type: 'bearer' })
  }

  if (method === 'POST' && pathname === '/api/v1/auth/register') {
    let body
    try {
      body = JSON.parse(await readBody(req))
    } catch {
      return send(res, 422, {
        detail: [{ loc: ['body'], msg: '请求体不是合法 JSON' }],
      })
    }

    const username = (body.username || '').trim()
    const password = body.password || ''

    const errors = []
    if (!USERNAME_RE.test(username)) {
      errors.push({
        loc: ['body', 'username'],
        msg: 'username must be 3-32 characters of letters, digits, _ or -',
      })
    }
    if (password.length < 8) {
      errors.push({
        loc: ['body', 'password'],
        msg: 'password must be at least 8 characters',
      })
    }
    if (errors.length) {
      return send(res, 422, { detail: errors })
    }

    if (users.has(username.toLowerCase())) {
      return send(res, 409, {
        detail: `username already taken: ${username}`,
      })
    }

    const user = {
      id: nextId++,
      username,
      password,
      is_active: true,
    }
    users.set(username.toLowerCase(), user)
    return send(res, 201, publicUser(user))
  }

  if (method === 'GET' && pathname === '/api/v1/auth/me') {
    const user = tokens.get(tokenOf(req))
    if (!user) {
      return send(res, 401, { detail: 'Could not validate credentials' })
    }
    return send(res, 200, publicUser(user))
  }

  return send(res, 404, { detail: `mock 没有实现这个接口: ${pathname}` })
}

export default function devAuthMock() {
  return {
    name: 'dev-auth-mock',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const pathname = new URL(req.url, 'http://localhost').pathname
        if (!pathname.startsWith('/api/v1/auth/')) return next()

        try {
          await handle(req, res, pathname)
        } catch (err) {
          send(res, 500, { detail: `mock 出错: ${err.message}` })
        }
      })

      server.config.logger.info(
        '  auth mock 已启用：demo / demo1234 可登录，disabled 会 403',
      )
    },
  }
}
