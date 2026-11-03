"""One small window, English by default, with a Chinese switch."""
import json
import ctypes as c
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .discovery import candidates, scan
from .storage import StorageEngine as Engine
from .doctor import report as storage_report
from .planner import make_plan, save_plan
from .windows import diagnose

TEXT = {
    'tagline': ('Inspect storage. Verify the move. Keep your work.', '看清存储位置，验证迁移结果，保留工作数据。'),
    'archive': ('Independent backup folder (optional, must be new)', '独立备份目录（可选，必须为新目录）'),
    'doctor': ('Storage doctor', '只读存储诊断'),
    'plan': ('Preview plan', '预览迁移计划'),
    'save_plan': ('Save plan', '导出计划'),
    'backup': ('Create independent backup', '创建独立备份'),
    'accept': ('Confirm app works', '确认使用正常'),
    'verify': ('Verify records', '核对记录'),
    'sqlite_option': ('Also check frozen SQLite chat databases', '同时检查聊天数据库（SQLite 冷副本）'),
    'confirm_accept': ('Have you reopened the app and checked history and tools?\n'
                       'This records your confirmation, not an automated UI test.\n\n',
                       '是否已重新打开应用，检查历史与工具使用正常？\n此处记录你的验收确认。\n\n'),
    'archive_note': ('An independent backup lets you reopen the app before releasing the retained original.',
                     '填写独立备份目录后，可先重开应用验收，再释放旧副本。'),
    'source': ('Source folder', '源文件夹'),
    'destination': ('New destination folder', '目标文件夹（必须为新目录）'),
    'browse': ('Browse…', '浏览…'),
    'discover': ('Find Codex folders', '发现 Codex 目录'),
    'scan': ('Check size', '检查占用'),
    'diagnose': ('Diagnose handles', '诊断占用'),
    'move': ('Verify & move', '校验并迁移'),
    'jobs': ('Recent migrations', '迁移记录'),
    'resume': ('Resume', '继续'),
    'release': ('Release space', '释放空间'),
    'rollback': ('Undo switch', '撤销切换'),
    'note': ('Close app writers before moving. Originals are retained; backups are never released automatically.',
             '迁移前关闭写入程序。旧副本会保留，独立备份不会自动删除。'),
    'ready': ('Ready · local only · no background service', '就绪 · 全程本地 · 无后台服务'),
    'confirm_move': ('Copy and verify this folder, then redirect the old path?\nThe original is retained.\n\n',
                     '复制并校验此目录，然后让原路径指向目标？\n旧副本会保留。\n\n'),
    'confirm_release': ('Re-verify both copies and permanently remove the retained original?\n'
                        'After release, Undo switch is no longer available.\n\n',
                        '重新校验两份数据后永久删除保留的旧副本？\n释放后无法直接撤销切换。\n\n'),
    'confirm_rollback': ('Restore the original path from the retained original?\nThe destination copy stays.\n\n',
                         '用保留的旧副本恢复原路径？\n目标盘副本仍会保留。\n\n'),
    'busy_close': ('An operation is running. Keep this window open until it finishes.',
                   '正在处理，请保持此窗口打开直至操作结束。'),
    'choose_job': ('Select a migration first.', '请先选择一条迁移记录。'),
    'diagnostic_note': ('Open handles are evidence, not proof of a blocking lock. Close the named app normally; '
                        'this tool never kills processes. A blank list is not a guarantee.',
                        '打开的句柄不一定阻止迁移。请正常关闭对应程序；工具不会强杀进程。空列表也不保证没有占用。'),
}


def human_bytes(size):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(size) < 1024 or unit == 'TiB':
            return '{:.1f} {}'.format(size, unit)
        size /= 1024


class App:
    def __init__(self, root, state_dir=None):
        self.root = root
        self.language = tk.StringVar(value='中文')
        self.source = tk.StringVar()
        self.destination = tk.StringVar()
        self.archive = tk.StringVar()
        self.check_sqlite = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.events = queue.Queue()
        self.busy = False
        self.engine = Engine(state_dir, lambda msg: self.events.put(('progress', msg)))
        self.translated = []
        self.actions = []
        root.title('Codex Storage Workbench')
        root.geometry('980x870')
        root.minsize(940, 820)
        root.configure(bg='#f6f7fb')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#f6f7fb', foreground='#182234')
        style.configure('TButton', padding=(12, 7), background='#e8edf6', borderwidth=0)
        style.map('TButton', background=[('active', '#d8e3f5')])
        style.configure('Accent.TButton', background='#2459c4', foreground='white')
        style.map('Accent.TButton', background=[('active', '#1749ae'), ('disabled', '#bac7df')])
        style.configure('Title.TLabel', font=('Segoe UI Semibold', 24))
        style.configure('Muted.TLabel', foreground='#627088')
        shell = ttk.Frame(root, padding=26)
        shell.pack(fill='both', expand=True)
        top = ttk.Frame(shell)
        top.pack(fill='x')
        ttk.Label(top, text='Codex Storage Workbench', style='Title.TLabel').pack(side='left')
        picker = ttk.Combobox(top, textvariable=self.language, values=['English', '中文'], state='readonly', width=9)
        picker.pack(side='right')
        picker.bind('<<ComboboxSelected>>', lambda event: self.translate())
        self.label(shell, 'tagline', style='Muted.TLabel').pack(anchor='w', pady=(3, 20))
        for key, var, command in [('source', self.source, self.choose_source),
                                   ('destination', self.destination, self.choose_destination),
                                   ('archive', self.archive, self.choose_archive)]:
            self.label(shell, key).pack(anchor='w', pady=(8, 5))
            row = ttk.Frame(shell)
            row.pack(fill='x')
            ttk.Entry(row, textvariable=var).pack(side='left', fill='x', expand=True, ipady=5)
            self.button(row, 'browse', command).pack(side='right', padx=(8, 0))
        row = ttk.Frame(shell)
        row.pack(fill='x', pady=(16, 8))
        for key, cmd in [('discover', self.find), ('scan', self.check_size), ('diagnose', self.check_handles)]:
            self.button(row, key, cmd).pack(side='left', padx=(0, 6))
        self.button(row, 'move', self.move, style='Accent.TButton').pack(side='right')
        secondary = ttk.Frame(shell)
        secondary.pack(fill='x', pady=(0, 8))
        for key, action in [('doctor', self.storage_doctor), ('plan', self.preview_plan),
                            ('save_plan', self.export_plan)]:
            self.button(secondary, key, action).pack(side='left', padx=(0, 6))
        self.label(shell, 'archive_note', style='Muted.TLabel', wraplength=880).pack(anchor='w', pady=(0, 4))
        self.label(shell, 'note', style='Muted.TLabel', wraplength=880).pack(anchor='w', pady=(2, 12))
        self.label(shell, 'jobs').pack(anchor='w', pady=(0, 6))
        self.job_picker = ttk.Combobox(shell, state='readonly')
        self.job_picker.pack(fill='x', ipady=3)
        database_option = ttk.Checkbutton(shell, variable=self.check_sqlite)
        self.translated.append((database_option, 'sqlite_option'))
        self.actions.append(database_option)
        database_option.pack(anchor='w', pady=(6, 0))
        row = ttk.Frame(shell)
        row.pack(fill='x', pady=8)
        for key in ('resume', 'backup', 'accept', 'verify', 'release', 'rollback'):
            self.button(row, key, lambda k=key: self.job_action(k)).pack(side='left', padx=(0, 7))
        self.output = tk.Text(shell, height=9, font=('Consolas', 10), bg='white', fg='#26334b',
                              relief='flat', padx=12, pady=10, wrap='word', state='disabled')
        self.output.pack(fill='both', expand=True, pady=(4, 10))
        self.bar = ttk.Progressbar(shell, mode='indeterminate')
        self.bar.pack(fill='x')
        footer = ttk.Frame(shell)
        footer.pack(fill='x', pady=(8, 0))
        ttk.Label(footer, textvariable=self.status, style='Muted.TLabel').pack(side='left')
        ttk.Label(footer, text='v' + __version__ + ' · beta', style='Muted.TLabel').pack(side='right')
        self.translate()
        self.refresh_jobs()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(100, self.poll)

    def t(self, key):
        return TEXT[key][1 if self.language.get() == '中文' else 0]

    def label(self, parent, key, **kwargs):
        widget = ttk.Label(parent, **kwargs)
        self.translated.append((widget, key))
        return widget

    def button(self, parent, key, command, **kwargs):
        widget = ttk.Button(parent, command=command, **kwargs)
        self.translated.append((widget, key))
        self.actions.append(widget)
        return widget

    def translate(self):
        for widget, key in self.translated:
            widget.configure(text=self.t(key))
        if not self.busy:
            self.status.set(self.t('ready'))

    def choose_source(self):
        p = filedialog.askdirectory()
        if p:
            self.source.set(p)

    def choose_destination(self):
        parent = filedialog.askdirectory(title=self.t('destination'))
        if parent:
            self.destination.set(str(Path(parent) / (Path(self.source.get()).name or 'CodexData')))

    def log(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text + '\n')
        self.output.see('end')
        self.output.configure(state='disabled')

    def run(self, function):
        if self.busy:
            return
        self.busy = True
        self.status.set('Working…' if self.language.get() == 'English' else '正在处理…')
        for button in self.actions:
            button.configure(state='disabled')
        self.bar.start(12)
        def work():
            try:
                self.events.put(('done', function()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=False).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.status.set(value[:100])
                else:
                    self.busy = False
                    self.bar.stop()
                    for button in self.actions:
                        button.configure(state='normal')
                    self.status.set(self.t('ready'))
                    if kind == 'error':
                        self.log('Error: ' + value)
                        messagebox.showerror('Codex Storage Workbench', value)
                    else:
                        if isinstance(value, dict):
                            value = {k: v for k, v in value.items() if k != 'manifest'}
                        self.log(self.describe(value))
                    self.refresh_jobs()
        except queue.Empty:
            pass
        self.poll_id = self.root.after(100, self.poll)

    def find(self):
        found = candidates()
        if found:
            self.source.set(next((p['path'] for p in found if not p['already_linked']), found[0]['path']))
        self.log('\n'.join('{}{}\n  {}'.format(p['category'], ' · linked' if p['already_linked'] else '',
                                                p['physical_path']) for p in found) or 'No known folders found.')

    def describe(self, value):
        zh = self.language.get() == '中文'
        if isinstance(value, dict) and value.get('mode') == 'read_only':
            lines = ['只读诊断完成' if zh else 'Read-only inspection complete']
            for item in value.get('locations', []):
                state = '✓' if item.get('exists') and not item.get('issue') else '—'
                lines.append('{} {}\n  {}\n  → {}'.format(state, item['kind'], item['path'],
                             item.get('physical_path', '未发现 / unavailable')))
                if item.get('same_storage_as'):
                    lines.append('  与其他入口使用同一存储 / shared storage')
                if item.get('issue'):
                    lines.append('  ' + item['issue']['code'])
            for item in value.get('packages', {}).get('packages', []):
                lines.append('{}: {}\n  {}'.format(item['name'], item['action'],
                                                   item.get('physical_cache', item.get('error', ''))))
            if not value.get('packages', {}).get('complete', True):
                lines.append('Windows 包查询未完成 / package query incomplete')
            if value.get('config_issues'):
                lines.append('配置路径需要检查 / config location needs review')
            return '\n'.join(lines)
        if isinstance(value, dict) and value.get('mode') == 'read_only_plan':
            lines = [('可以执行' if value['can_apply'] else '需先处理阻断项') if zh else
                     ('Ready for execution' if value['can_apply'] else 'Blocked before execution'),
                     value['source'] + '\n→ ' + value['destination']]
            if value.get('archive_path'):
                lines.append(('独立备份：' if zh else 'Independent backup: ') + value['archive_path'])
            for item in value.get('space_budget', []):
                lines.append('{}: {} / {}'.format(item['drive'],
                             human_bytes(item['required_bytes']), human_bytes(item['available_bytes'])))
            for item in value.get('blockers', []):
                lines.append(item['code'] + ': ' + item['message'])
            if value.get('saved_to'):
                lines.append(('已保存：' if zh else 'Saved: ') + value['saved_to'])
            return '\n'.join(lines)
        if not isinstance(value, dict):
            return str(value)
        if 'phase' in value:
            phase = {'migrated': '已切换，原件保留', 'released': '已释放旧副本', 'rolled_back': '已恢复原路径',
                     'copying': '复制中', 'switch_pending': '等待切换', 'releasing': '清理待继续',
                     'releasing_archive': '独立备份清理待继续', 'already_on_target': '已经位于目标目录'}.get(value['phase'], value['phase'])
            lines = [phase if zh else value['phase'].replace('_', ' ').capitalize(),
                     value['source'] + '\n→ ' + value['destination']]
            size = value.get('summary', {})
            lines.append(('已校验：' if zh else 'Verified: ') + '{} files · {} links · {}'.format(
                size.get('files', 0), size.get('links', 0), human_bytes(size.get('bytes', 0))))
            if 'free_after' in value:
                lines.append(('当前可用空间：' if zh else 'Free now: ') + human_bytes(value['free_after']))
                lines.append(('可用空间变化：' if zh else 'Observed free-space change: ') + human_bytes(value['observed_free_change']))
            if value.get('archive'):
                saved = value['archive']
                lines.append(('独立备份：' if zh else 'Independent backup: ') + saved['path'] + ' · ' + saved['state'])
            if value.get('acceptance'):
                lines.append(('使用验收：' if zh else 'Acceptance: ') + value['acceptance']['type'])
            if value.get('checks'):
                lines.append(json.dumps(value['checks'], ensure_ascii=False, indent=2))
            if value.get('sqlite'):
                lines.append('SQLite: ' + value['sqlite']['status'])
            if value['phase'] == 'migrated':
                lines.append(('下一步：重开应用验收，再确认使用正常并释放旧副本。' if zh else
                              'Next: reopen the app, confirm it works, then release the original.')
                             if value.get('archive', {}).get('state') == 'verified' else
                             ('下一步：创建独立备份，或在应用保持关闭时释放原件。' if zh else
                              'Next: create an independent backup, or release while apps remain closed.'))
            return '\n'.join(lines)
        if 'handles' in value:
            lines = ['{} · PID {}\n  {}'.format(h['process'], h['pid'], h['path']) for h in value['handles']]
            if not lines:
                lines.append('未发现可见占用。' if zh else 'No visible matching handles.')
            if value.get('incomplete'):
                lines.append(('诊断不完整：' if zh else 'Incomplete diagnostic: ') + value.get('error', ''))
            if value.get('inaccessible_processes'):
                lines.append(('无法检查的进程数：' if zh else 'Inaccessible processes: ') + str(value['inaccessible_processes']))
            return '\n'.join(lines)
        if value.get('already_linked'):
            return ('已是目录链接，实际位置：' if zh else 'Already linked. Actual location: ') + value['physical_path']
        if 'bytes' in value:
            return '{} files · {} links · {}'.format(value['files'], value['links'], human_bytes(value['bytes']))
        return json.dumps(value, ensure_ascii=False, indent=2)

    def check_size(self):
        path = self.source.get()
        self.run(lambda: scan(path))

    def check_handles(self):
        path = self.source.get()
        self.log(self.t('diagnostic_note'))
        self.run(lambda: diagnose(path))

    def move(self):
        source, destination = self.source.get(), self.destination.get()
        archive = self.archive.get().strip() or None
        if not source or not destination:
            messagebox.showerror('Codex Storage Workbench', self.t('source') + ' / ' + self.t('destination'))
            return
        if messagebox.askyesno('Codex Storage Workbench', self.t('confirm_move') + source + '\n→ ' + destination):
            self.run(lambda: self.engine.migrate(source, destination, archive))

    def refresh_jobs(self):
        try:
            self.job_list = self.engine.jobs()
            self.job_picker['values'] = ['{} · {} · {}'.format(j['phase'], Path(j['source']).name, j['id'][:8])
                                         for j in self.job_list]
            if self.job_list:
                self.job_picker.current(0)
        except Exception as exc:
            self.log(str(exc))

    def job_action(self, action):
        index = self.job_picker.current()
        if index < 0:
            messagebox.showinfo('Codex Storage Workbench', self.t('choose_job'))
            return
        job = self.job_list[index]
        if action == 'release' and job.get('archive'):
            self.log(('将核对独立备份和冻结旧副本，保留活动数据。' if self.language.get() == '中文'
                      else 'Will verify independent backup and retained original; active data stays unchanged.'))
        if action == 'backup':
            path = self.archive.get().strip()
            if not path:
                self.choose_archive()
                path = self.archive.get().strip()
            if path:
                self.run(lambda: self.engine.seal(job['id'], path))
            return
        if action == 'verify':
            sqlite = self.check_sqlite.get()
            self.run(lambda: self.engine.verify(job['id'], sqlite=sqlite))
            return
        if action != 'resume' and not messagebox.askyesno('Codex Storage Workbench', self.t('confirm_' + action) +
                                                        job['source'] + '\n→ ' + job['destination']):
            return
        self.run(lambda: getattr(self.engine, action)(job['id']))

    def choose_archive(self):
        parent = filedialog.askdirectory(title=self.t('archive'))
        if parent:
            self.archive.set(str(Path(parent) / ((Path(self.source.get()).name or 'CodexData') + '-backup')))

    def storage_doctor(self):
        self.run(lambda: storage_report(deep=False))

    def preview_plan(self):
        source, destination = self.source.get(), self.destination.get()
        archive = self.archive.get().strip() or None
        if not source or not destination:
            messagebox.showerror('Codex Storage Workbench', self.t('source') + ' / ' + self.t('destination'))
            return
        self.run(lambda: make_plan(source, destination, archive, self.engine.state_dir))

    def export_plan(self):
        source, destination = self.source.get(), self.destination.get()
        archive = self.archive.get().strip() or None
        if not source or not destination:
            messagebox.showerror('Codex Storage Workbench', self.t('source') + ' / ' + self.t('destination'))
            return
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='migration-plan.json',
                                           filetypes=[('JSON', '*.json')])
        if path:
            def work():
                result = make_plan(source, destination, archive, self.engine.state_dir)
                save_plan(result, path)
                result['saved_to'] = path
                return result
            self.run(work)

    def close(self):
        if self.busy:
            messagebox.showinfo('Codex Storage Workbench', self.t('busy_close'))
        else:
            self.root.after_cancel(self.poll_id)
            self.root.destroy()


def launch(state_dir=None):
    # Hide only a console created for this executable, never the caller's terminal.
    import sys
    if getattr(sys, 'frozen', False):
        k = c.WinDLL('kernel32')
        ids = (c.c_uint32 * 2)()
        if k.GetConsoleProcessList(ids, 2) == 1:
            k.GetConsoleWindow.restype = c.c_void_p
            u = c.WinDLL('user32')
            u.ShowWindow.argtypes = [c.c_void_p, c.c_int]
            u.ShowWindow(k.GetConsoleWindow(), 0)
    root = tk.Tk()
    App(root, state_dir)
    root.mainloop()
