# 把项目上传到 GitHub

建议仓库名：`wechat-lite`。

建议描述：`Docker部署的Linux微信私聊自动回复助手，支持模型API、好友白名单和聊天风格管理。`

建议Topics：`wechat`、`chatbot`、`linux`、`docker`、`python`、`llm`、`desktop-automation`。

## 用命令行上传

1. 解压发布源码包，进入wechat-lite目录。上传的是这里的项目文件，不是整个私人部署目录。
2. 在GitHub创建一个空仓库，自选Public或Private；不要勾选自动生成README、.gitignore、许可证，因为本包已经有。
3. 电脑安装Git，在项目根目录打开PowerShell或终端。
4. 第一次使用Git且未配置作者时，设置此仓库的作者信息，可以使用GitHub账户设置中的noreply邮箱。

```bash
git init -b main
git config user.name "你的GitHub用户名"
git config user.email "你的GitHub邮箱或noreply邮箱"
git add .
git status --short
git commit -m "Initial release of WeChat Lite"
git remote add origin https://github.com/你的GitHub用户名/wechat-lite.git
git push -u origin main
```

如果Git已有正确作者信息，两条git config可以省略。HTTPS推送按Git提示使用凭据管理器/浏览器认证或你自己的Token，不把Token写入仓库或remote URL，不用GitHub网页登录密码当Git密码。

根目录应该直接显示README.md、LICENSE、compose.yaml、setup.sh等，不要把它们全部再放进一层压缩包上传。

## 用 GitHub Desktop 上传

解压源码到电脑，GitHub Desktop登录后通过File → Add local repository选择源码目录；若提示不是Git仓库，点击创建仓库，使用当前目录。查看Changes并提交初始版本，再Publish repository。是否勾选Keep this code private由你决定。不要用部署后的目录替代源码。

## 提交前后检查

- 本包初始内容没有真实Key、密码、微信data或个人聊天风格，使用通用示例。
- .gitignore已排除部署时生成的配置、.env、data、备份、数据库、样本、private和缓存。
- 已被Git跟踪的文件不会因为后来加入.gitignore而自动解除跟踪；不要把旧的部署目录直接git add。
- 原创代码预置MIT许可证，允许使用、修改和分发并保留许可声明；上游微信客户端等不属于此许可。
- 上传后Actions会触发自动检查。绿色测试只能验证模拟逻辑和语法，不能保证每个微信版本都能识别。

## 打包发布版本

验证后可以执行：

```bash
python tools/package_release.py
```

它只收集受控源码路径，并拒绝检测到的敏感文件/标记，生成dist/wechat-lite-source.zip和dist/wechat-lite-source.tar.gz。再将这两个文件手工附到GitHub Release。发布工具不会自动联网、创建仓库或上传。
