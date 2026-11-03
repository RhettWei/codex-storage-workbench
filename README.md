# Codex Storage Workbench

Windows 上的 Codex 存储诊断与可验证迁移工具。提供中英文桌面界面和同一套 CLI，支持在保留原路径的情况下搬迁普通数据目录。

本项目基于 [ASEXPIAO/codex-relocate](https://github.com/ASEXPIAO/codex-relocate) 的 MIT 实现扩展。上游来源与固定提交见 [UPSTREAM.md](UPSTREAM.md)，原始说明保留在 [README.upstream.md](README.upstream.md)。当前版本为 0.2.0.dev1，面向 Windows 10/11 x64、本机固定 NTFS 磁盘。

## 新增能力

- **只读存储诊断**：识别 CODEX_HOME、CODEX_SQLITE_HOME、配置中的 sqlite_home、项目目录、工具和运行时缓存；区分逻辑入口和物理位置，标记重复计数、权限问题与扫描不完整。
- **Windows 包状态识别**：读取安装位置和 LocalCache 的最终物理路径。已经在目标盘的包标记为复用；不重复复制受保护缓存。
- **可审查的计划**：预览阻断原因、源目录身份，以及目标和独立备份在同一卷上的合计空间预算。执行保存的计划时重新检查环境。
- **独立备份与使用验收**：保存冻结旧副本的独立备份，校验通过后可以重开应用继续工作；记录用户验收，再清理旧副本，保留新增数据。
- **清理中断恢复**：逐次核对完整独立备份与剩余旧副本，只删除本任务保留的目录；不跟随子链接，不把回滚用于覆盖新数据。
- **SQLite 冷副本检查**：同时检查根目录和 sqlite/ 中的 .sqlite、.db；WAL/journal 复制到一次性目录，源数据库不做 checkpoint。
- **完整 JSON 发布**：唯一临时文件、关闭与刷新后替换、有限的共享冲突重试；不会把半写入清单当作正式结果。

保留上游的 SHA-256、NTFS 文件附加数据流、链接校验、句柄诊断和普通迁移模式。

## 使用 Windows 便携包

1. 解压整个 Windows ZIP，保留 EXE 旁的 _internal 目录。当前便携包是未做代码签名的开发预览版。
2. 将工具放在准备迁移的目录之外；点击 Start.cmd，或者打开 CodexStorageWorkbench.exe。
3. 先点“只读存储诊断”，再选择源目录、尚不存在的目标目录；需要先验收再清理时，填写尚不存在的独立备份目录。
4. 点“预览迁移计划”，处理显示的占用、权限或空间问题。
5. 关闭会写入源目录的应用后，执行“校验并迁移”。旧目录会作为本任务的冻结副本保留。
6. 独立备份显示 verified 后，重新打开应用，检查历史、文件和工具；在迁移记录中点“确认使用正常”。
7. 点“释放空间”。工具复核独立备份和冻结旧副本，只清理旧副本，活动目录继续保留最新数据。

只有用户主动操作才会移动或删除选定目录。不会停止服务、结束进程、放宽源目录权限、解密文件或配置系统自启动；副本会按原访问规则设置 DACL。

不使用独立备份时，沿用上游保守流程：应用保持关闭，当前目标一旦发生变化，自动清理和回滚会拒绝执行。

## 从源码运行

需要 Python 3.11+ 与 Tkinter。运行时只使用标准库。下面从项目根目录执行：

~~~powershell
python -m codex_relocate gui
python -m codex_relocate doctor --target-drive D: --redact
~~~

Start.cmd 优先使用本项目 .venv 中的 Python，工具状态写到项目 local-state；该目录被 Git 忽略。CLI 默认状态目录为当前用户 LOCALAPPDATA 下的 CodexStorageWorkbench/jobs，可用 --state-dir 指定物理路径。已迁移目录的 C 盘兼容入口不能作为日志目录的链接祖先。

## CLI 工作流

以下是示例路径，请替换为自己的实际目录，并先创建计划、日志和目标目录的上级文件夹：

~~~powershell
python -m codex_relocate doctor --target-drive D: --redact

python -m codex_relocate --state-dir D:\MigrationJobs\jobs plan C:\Users\Example\.codex D:\AIData\CodexHome --archive D:\AIBackups\CodexHome --output D:\MigrationJobs\plan.json

python -m codex_relocate apply D:\MigrationJobs\plan.json --yes

python -m codex_relocate --state-dir D:\MigrationJobs\jobs jobs
python -m codex_relocate --state-dir D:\MigrationJobs\jobs verify JOB_ID --sqlite
~~~

重新打开应用并实际验收后，再记录验收和清理：

~~~powershell
python -m codex_relocate --state-dir D:\MigrationJobs\jobs accept JOB_ID --yes
python -m codex_relocate --state-dir D:\MigrationJobs\jobs cleanup JOB_ID --yes
~~~

其他操作：

~~~powershell
# 已切换的任务也能从保留的冻结旧副本创建独立备份。
python -m codex_relocate --state-dir D:\MigrationJobs\jobs backup JOB_ID D:\AIBackups\NewBackup

# 继续中断的复制、备份或清理。
python -m codex_relocate --state-dir D:\MigrationJobs\jobs resume JOB_ID

# 只有不会覆盖新数据时才能撤销切换。
python -m codex_relocate --state-dir D:\MigrationJobs\jobs rollback JOB_ID --yes
~~~

JSON 结果写到 stdout，进度和错误写到 stderr。plan 返回 2 表示有阻断项；执行错误返回 1。doctor 默认只读取已知目录元数据和配置中的路径字段，--deep 才枚举目录元数据。深度统计不读取文件内容，也不跟随子链接；显示的大小不包含附加数据流和磁盘分配开销。迁移的空间预算和内容校验会另外包含文件附加数据流。

## 安全与范围

- 普通目录迁移、独立备份和清理才属于执行范围；WindowsApps 和 Windows 包私有缓存只提供只读诊断。应用本体需要 Windows“设置”或原生部署 API 移动。
- EFS、云盘占位文件、不认识的重解析类型、目录附加数据流、已有目标、路径重叠等会被拒绝。拒绝后保留原数据。
- DACL 沿用上游复制规则。文件所有者、审计元数据与硬链接拓扑不保证保留；无权读取的子目录不会通过放宽 ACL 来绕过。此版本未实现自动 SYSTEM 辅助程序。
- “独立备份”要求备份根是独立目录，普通文件不能硬链接到活动数据或旧副本；目录链接仍按链接对象保存，不包含外部链接目标的数据。
- 同一磁盘上的独立目录备份不等于跨物理磁盘备份。需要抵御磁盘故障时，应另保存到其他物理介质。
- 先停止写入者再迁移。文件复制与多轮哈希不是整个目录的原子快照。SQLite 检查仅针对冻结副本，不提供整个运行中应用的在线一致性快照。
- 用户验收标记由用户确认产生，不能替代实际登录、历史和工具检查。verify 会明确把活动数据检查限定为路径与目录身份，不会宣称校验了正在变化的所有内容。
- 任务日志包含个人路径、哈希和链接信息。doctor 的 --redact 是本地脱敏辅助，分享前仍应预览。个人 .codex、认证、聊天数据库、真实清单和本地备份不进入此源码仓库。
- 意外断电若发生在创建对象与记录其身份之间，工具可能保留无法自动认领的空目录；会拒绝猜测其归属。遇到这类情况保留原件、目标、备份与日志后检查。

更详细的上游边界见 [docs/SAFETY.md](docs/SAFETY.md)，本次扩展的设计与测试见 [docs/WORKBENCH.md](docs/WORKBENCH.md)。

## 开发与构建

~~~powershell
python -m unittest discover -s tests -v
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name CodexStorageWorkbench run.py
~~~

也可以在已激活构建环境后运行 scripts/build.ps1。测试在系统临时目录创建人造文件、真实 Junction 和 SQLite 数据库。它们不需要迁移自己的 Codex 数据。验证版本与结果见 [VALIDATION.md](VALIDATION.md)。

MIT；保留上游版权和许可证。详见 [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)。
