# 上游与第三方组件

本仓库的原创脚本、后台和界面自动化代码使用 MIT License。

Dockerfile 基于 [LinuxServer Weixin](https://github.com/linuxserver/docker-weixin) 镜像，运行腾讯 Linux 微信客户端。基础镜像、微信、Python、PyGObject、AT-SPI、X11/XTest 等依赖使用各自的许可证或服务条款；本仓库的 MIT 许可证不覆盖这些上游软件。

仓库不包含微信客户端二进制、Docker镜像、腾讯官方API授权或模型服务账号。使用模型API需要自己的Key，模型服务遵循供应商条款。

本项目是独立的客户端界面自动化工具，与腾讯、微信、LinuxServer和模型供应商没有官方隶属关系。
