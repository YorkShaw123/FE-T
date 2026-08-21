"""
雨生编辑器 - CloudStudio 云端演示专用启动入口

与 server/app.py 的区别（不改动任何已有代码，仅新增本入口）：
  - app.py 的 ``__main__`` 入口固定监听 127.0.0.1（本机开发/桌面 Sidecar 用），
    无法被 CloudStudio 端口转发访问；
  - 本入口复用同一个 ``create_app`` 应用工厂，改绑 0.0.0.0:8000，
    供 CloudStudio 沙盒对外暴露服务。

架构说明：本项目为 Flask 单服务架构，前端页面（templates/static）与 API
（/api/*）由同一端口直接提供，前端全部使用相对路径请求，无需 Vite 代理，
也不存在跨域问题。
"""
import os

from app import create_app

app = create_app('production')


@app.after_request
def _allow_cloud_preview_embedding(response):
    """允许 CloudStudio 内置浏览器以 iframe 形式内嵌预览页面。

    app.py 已为响应设置 ``X-Frame-Options: DENY``（桌面版安全默认值，
    不修改）。云端演示场景下，通过 CSP ``frame-ancestors`` 放宽限制：
    在现代浏览器中该指令优先于 X-Frame-Options 生效。仅影响本入口启动
    的云端演示服务，不影响桌面版与本机开发模式。
    """
    response.headers['Content-Security-Policy'] = 'frame-ancestors *'
    return response


if __name__ == '__main__':
    port = int(os.environ.get('FLORA_PORT', '8000'))
    print('=' * 60)
    print('  雨生编辑器 (Flora Editor) — CloudStudio 云端演示模式')
    print(f'  监听地址: http://0.0.0.0:{port}')
    print('  前端页面与 API 由同一端口提供（Flask 单服务架构）')
    print('=' * 60)
    # debug=False：云端演示无需热重载；Flask 开发服务器默认多线程，
    # 可支撑页面请求与 SSE 流式生成接口并发。
    app.run(host='0.0.0.0', port=port, debug=False)
