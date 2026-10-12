# 贡献说明

先描述具体问题、微信界面版本和复现步骤，再提交小范围修改。涉及好友信息、密钥和私聊截图时先脱敏。

## 本地检查

Python 3.11及以上，测试只依赖标准库：

```bash
python -m unittest discover -s tests -p 'test_*.py'
node --check wechat-desktop-bot/web/app.js
for file in *.sh wechat-desktop-bot/service wechat-desktop-bot/admin-service; do sh -n "$file"; done
WECHAT_DESKTOP_PASSWORD=ci-example-password docker compose -f compose.yaml config --quiet
```

最后两个命令在Linux/兼容Shell执行。真实GUI运行需要Docker镜像中的PyGObject/AT-SPI/X11，不要求把这些装进单元测试环境。CI没有真实微信登录和模型调用。

修改收发逻辑时验证：历史基线不回复、本人消息不触发模型、重复文本区分、草稿保护、同一好友顺序、并发队列、限流、发送后确认。每次模型尝试必须计入调用额度；不要把思考内容当正文发送。

使用LF换行，不提交config.json、数据库、样本、.env或data。新增供应商参数写入配置示例和文档，不硬编码密钥。不要直接执行来自消息、模型输出或聊天导出文件的命令。
