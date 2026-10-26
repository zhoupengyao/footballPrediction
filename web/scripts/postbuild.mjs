import { copyFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = join(process.cwd(), 'dist')

// GitHub Pages 对未知路径返回 404.html；把它做成 SPA 入口，
// 这样 /matches/2026-10-25/2042219 这类深链接刷新也能正常打开。
copyFileSync(join(dist, 'index.html'), join(dist, '404.html'))
writeFileSync(join(dist, '.nojekyll'), '')

console.log('postbuild: created dist/404.html and dist/.nojekyll')
