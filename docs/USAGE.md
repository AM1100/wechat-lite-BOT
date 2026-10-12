# 中文使用说明

## 部署与目录

宿主机安装Docker Engine和Compose v2后，在源码根目录执行 `sudo sh setup.sh`。系统无需桌面或Python；Python及界面依赖由Dockerfile安装。首次构建需要联网拉取基础镜像和apt软件包，不是离线部署。

主要目录：

```text
compose.yaml                       唯一启动配置
setup.sh / start.sh / stop.sh       安装、启动、停止
logs.sh                            实时日志
desktop-password.sh                桌面密码查询
reset-admin-password.sh             后台密码重置
backup.sh                          一致备份
prompts/natural-chat.txt            通用风格示例
wechat-desktop-bot/config.example.json  可提交的初始模板
wechat-desktop-bot/config.json      安装后生成的私人配置
data/                              微信持久化数据
.env                               安装后生成的桌面密码
tests/                             模拟单元测试与独立配置样例
```

不要用模板覆盖已部署的config.json。再次运行setup会保留已有配置和密码，重建镜像。日常用start.sh。基础镜像使用latest，重建时可能下载不同微信版本；正常工作时保留已有镜像，新版本要重新验证控件识别。

普通账号执行Docker、初始化或备份命令时使用sudo，避免Docker socket权限错误。镜像内部账号abc的UID/GID固定1000，脚本据此设置机器人目录权限。

## 微信界面和多人监听

SSH隧道要在访问网页的电脑上建立，不要在服务器上转发到自身。桌面为HTTPS3001，后台为HTTP8787，两者都只映射服务器127.0.0.1。

微信保持登录、窗口展开，建议最大化。把白名单私聊置顶并保持在左侧列表可见；名字与聊天标题完全一致，避免同名群聊或同名好友。一个微信窗口即可，程序轮流切换好友，不需多个独立窗口。

先开启仅监听，保存，等初始化后发新消息。`LISTENING initialized=1 friends=3` 表示目前只初始化了1位，要确认其他好友也能被打开。重启或配置变化会重建基线，不回复启动前的历史消息。未发送的内存队列不会随重启或迁移保存。

多人模型请求可排队，GUI发送仍按次操作。消息瞬间滚出可见区、人工切换或输入草稿可能干扰识别；避免在自动回复时操作同一个输入框。背景运行不要求浏览器或SSH隧道一直打开，但容器中的微信不能关闭或最小化。

## 模型参数和预算

初始建议：并发1、全局请求间隔10秒、同一好友间隔20秒、合并等待4秒、最长合并12秒、超时60秒、临时连接错误最多额外尝试1次。429会额外暂停全局请求，不无限重试。额度、失败或等待原因查看后台状态和日志。

默认日常每天60次、每位好友20次；失败和重试也占额度。后台测试与风格分析另计，每天合计10次。适量调整即可；供应商429也可能是余额/日额度，不一定是并发高。

默认3轮上下文、1600字符历史、800字符输入、250字符回复。更多上下文和更长提示词会增加输入token；关闭思考适合简短聊天。

供应商附加参数是一个JSON对象，不要套 `extra_body`。更换供应商时同时修改模型名、API地址和参数。DeepSeek使用 `thinking.type=disabled`；Qwen等模型的开关以对应供应商文档为准。Key不贴进日志或GitHubIssue。

## 风格样本

只导入自己的发言，无需标发送人。双方导出的聊天先提取本人消息，避免模仿对方。上传上限500KB，分析采样最多约6000字符。上传仅保存在服务器；点击分析才发给模型。分析结果需要保存才生效。

“聊天风格描述”和“回复人设与规则”各最多10000字符。完整版合并提示词放在回复规则，风格描述清空，避免重复。发送前会移除空白行并保留单次换行。个人风格和聊天记录建议放private/，这个目录被Git忽略。

## 密码

桌面账号wechat，密码在.env，可用desktop-password.sh查询。后台账号admin，初始密码只在第一次启动日志显示；之后保存哈希，不可还原，忘记用reset-admin-password.sh。后台更换密码后旧会话失效。SSH账号密码与上述两者无关。

## 备份迁移

执行 `sudo sh backup.sh`，脚本停止容器、备份.env/compose/data/程序配置和数据库/提示词，然后启动容器。备份在backups/，包含密钥、密码、微信数据，只私下保存。

新设备获取此仓库的源码，进入项目目录，再把备份恢复到这里：

```bash
sudo tar -xzf /上传路径/wechat-backup-日期.tar.gz
sudo sh setup.sh
```

完整备份会恢复备份当时的代码和Compose，运行setup保留恢复的配置及密码，微信可能要重新扫码。恢复到新目录，避免覆盖正在运行的部署。停止旧设备后再启用新设备。迁移不能保证客户端登录态保留。

如只迁移设置，旧端停止后私下复制机器人目录里的config.json、admin.json、state.sqlite及其存在的-wal/-shm、admin-usage.sqlite、sample.txt/sample.json到新项目对应目录。不要覆盖新代码，不复制bot.lock/runtime.json；运行setup修正权限，微信重新登录。不要把迁移数据提交到GitHub。

## 排错

查看最近日志：

```bash
sudo docker compose -f compose.yaml ps
sudo docker compose -f compose.yaml logs --since=5m --tail=150 weixin
```

| 情况 | 检查方向 |
| --- | --- |
| Address already in use | 电脑上的隧道端口已被占用，关闭重复隧道或换本地端口，浏览器同步改地址 |
| SSH channel Connection refused | 目标容器/服务尚未启动，确认端口映射和日志、主机IP |
| HTTP request sent to HTTPS port | 桌面地址要用HTTPS，后台用HTTP |
| Cannot locate chat controls / StopIteration | 登录状态、展开微信窗口、打开私聊、列表可见、控件版本；启动初期可短暂等待 |
| Model returned no text | 接口没有非空content；核对思考开关、输出上限，仍失败需看finish_reason和字段格式 |
| TimeoutError | 接口/网络慢，检查连通性与超时配置 |
| Temporary failure in name resolution | DNS或网络波动，检查容器DNS；127.0.0.11可能只是正常Docker内部转发 |
| HTTP429 | 频率、额度或余额；按供应商限制降低频率，不频繁测试 |
| 等待发送确认 | 已点发送但尚未识别新发出消息，先等待；不立即重发 |
| 已启动但不回复 | 仅监听开关、启用、白名单、初始化、可见聊天、草稿、调用额度；初始化后发新消息 |
| 网页输入框仍是旧限制 | Ctrl+F5，确认隧道指向正确设备，重新粘贴被截断的文字 |

Compose默认DNS为223.5.5.5和119.29.29.29；网络限制这些地址时改成可达DNS，然后执行start.sh应用配置。不要混用旧项目的多个Compose文件。

目前自动化仅依据可见控件和颜色判断。真实微信客户端和提供商网络环境需在自己的Linux设备验证，单元测试不能替代实际收发验证。
