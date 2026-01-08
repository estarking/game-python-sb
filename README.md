# game-python-sb

直接运行即可，无需修改任何东西

单端口模式：启用 HY2 + HTTP(订阅) + Argo  可以手动选择tuic
多端口模式：TUIC + HTTP(订阅) + Argo + HY2 + REALITY

如果系统无法自动获取到可用端口，则需自己手动新建 /ports.txt 文件，一行一个端口号

启动示例：
- 单端口：SERVER_PORT="443" python app.py
- 多端口：SERVER_PORT="443 8443" python app.py
- 不使用环境变量：在 app.py 中设置 DEFAULT_PORTS，然后直接运行 python app.py

Argo 固定隧道：
- 设置固定隧道 token：ARGO_TOKEN="xxxx"
- 设置固定域名：ARGO_DOMAIN="your.example.com"
- 修改本地转发端口：ARGO_PORT="8081"
- 运行：ARGO_TOKEN="xxxx" ARGO_DOMAIN="your.example.com" python app.py

Python 环境：
- 需要 Python 3.8+（推荐 3.10+）
- 依赖仅标准库，equirements.txt 为空
