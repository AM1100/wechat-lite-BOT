# WeChat Lite · Linux 微信自动回复助手

在 Linux 小主机上运行微信客户端，通过本地界面自动化读取指定好友的文字消息，再调用模型 API 生成回复。带中文网页后台，可以更换模型、管理白名单和自定义聊天风格。

使用 Docker 部署，宿主机无需安装图形桌面。模型使用兼容 Chat Completions 的 API，没有代理工具循环。微信接入不需要购买协议授权；模型调用仍由供应商收费。

## 功能

- 指定私聊白名单，轮流监听同一微信窗口内可见的好友会话。
- 多人消息队列、连续消息合并、全局请求间隔、超时限次重试与429等待。
- 发送后确认；不确定是否成功时保留状态，避免立即重复发送。
- 网页配置接口地址、API Key、模型和运行参数。
- TXT文字样本导入及风格提炼，两个提示词输入框支持10000字符。
- 仅监听模式、每日调用额度、短期上下文和密码管理。
- 启动、停止、日志、密码查询和停机备份脚本。

## 环境与边界

推荐 Debian 12、64位 Intel/AMD CPU、8GB内存、Docker Engine和Compose v2。基础镜像也提供ARM64，但本项目的界面识别尚未在ARM设备验证。

当前仅处理私聊文字；不自动理解图片、语音、表情和文件。微信必须登录、窗口展开，白名单聊天置顶并在左侧列表可见。机器人依赖微信控件和气泡颜色，微信版本、主题、缩放变化可能影响识别；它不具备协议API的稳定消息ID。

## 快速开始

在服务器解压源码或克隆仓库，进入项目根目录：

```bash
sudo sh setup.sh
```

首次运行会生成密码和本地 `wechat-desktop-bot/config.json`，构建镜像并启动容器。默认仅监听、不调用模型、不发送。

在你自己的电脑终端建立SSH隧道，把用户名和主机IP替换为实际值：

```bash
ssh -N -o ExitOnForwardFailure=yes -L 13001:127.0.0.1:3001 -L 18787:127.0.0.1:8787 SSH用户名@服务器IP
```

| 页面 | 浏览器地址 | 用户名 | 密码 |
| --- | --- | --- | --- |
| 微信远程桌面 | `https://127.0.0.1:13001` | `wechat` | 服务器执行 `sudo sh desktop-password.sh` |
| 管理后台 | `http://127.0.0.1:18787` | `admin` | 首次安装日志，忘记则执行 `sudo sh reset-admin-password.sh` |

远程桌面使用自签名HTTPS。确认地址是自己的隧道后接受证书提示。后台和桌面密码是两套，SSH密码是服务器账号密码。

1. 在远程桌面扫码登录微信，保持微信窗口展开，打开测试好友私聊。
2. 在后台加入准确的私聊备注名，将聊天置顶；保持“仅监听，不回复”开启并保存。
3. 等日志出现 `LISTENING`，让好友发一条新文字，确认 `DRY_RUN received=...`。
4. 填写模型API Key和模型参数并保存；关闭“仅监听，不回复”，等监听重新就绪后测试新消息。

启动时已有消息作为历史跳过。所有目标好友都应可见、可打开并完成初始化。运行正常后可以关闭浏览器和电脑上的隧道，但服务器与其中的微信程序须保持运行。

## 模型与聊天风格

配置模板预置官方DeepSeek Flash：`https://api.deepseek.com/v1`、`deepseek-flash`、`max_tokens=512`，附加参数为：

```json
{"thinking": {"type": "disabled"}}
```

其他供应商使用自己的模型ID和参数；本程序支持根地址或完整 `/chat/completions` 地址，不使用 `/responses`。API Key 在本地配置保存，网页读取时不回显；留空保存会保留旧Key。

`prompts/natural-chat.txt` 是通用示例，可粘贴到“回复人设与规则”。两栏风格要求不要重复；个人聊天导出和定制风格请放在被忽略的 `private/` 目录。上传样本只保存在本地；点击提炼才会发送采样文本给当前模型。风格提炼是提示词整理，不是训练模型。

## 日常命令

```bash
sudo sh start.sh                 # 启动已有部署
sudo sh stop.sh                  # 停止微信、机器人和后台
sudo sh logs.sh                  # 实时日志，Ctrl+C退出查看
sudo sh desktop-password.sh      # 查询桌面密码
sudo sh reset-admin-password.sh  # 重置后台密码
sudo sh backup.sh                # 短暂停机备份，之后重新启动
```

部署只使用一份 `compose.yaml`，含DNS配置。容器在Docker启动后自动恢复，手动停止过则需要重新启动。不要同时手工运行第二份机器人。

## 文档与开发

- [完整中文使用说明](docs/USAGE.md)：参数、备份迁移、常见问题。
- [上传到GitHub](docs/GITHUB_UPLOAD.md)：第一次发布的步骤。
- [贡献说明](CONTRIBUTING.md)：本地验证与提交方法。
- [安全与个人数据](SECURITY.md)。
- [更新记录](CHANGELOG.md)。

Python单元测试只使用模拟模型、模拟GUI和临时本地HTTP后台，不需要真实微信或API Key：

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

GitHub Actions配置了Python测试、Shell语法、网页JS语法和Compose配置检查。实际镜像构建和微信收发仍需要Linux设备验证。

## 许可证与上游

原创代码使用 [MIT License](LICENSE)。上游依赖及微信客户端使用各自许可证和条款，见 [第三方说明](THIRD_PARTY_NOTICES.md)。基础镜像文档见 [LinuxServer Weixin](https://docs.linuxserver.io/images/docker-weixin/)，DeepSeek参数见 [官方思考模式说明](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)。
