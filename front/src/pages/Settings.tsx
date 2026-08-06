import { useEffect, useState } from "react";
import {
  Cloud,
  Copy,
  Eye,
  EyeOff,
  FileJson,
  Loader2,
  Mail,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  UploadCloud,
  X,
} from "lucide-react";
import { api, type ConfigFileSnapshot } from "@/lib/api";
import { copyText } from "@/lib/utils";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  PageHeader,
  Select,
  Switch,
  Toast,
} from "@/components/ui";

const PROVIDERS = [
  {
    value: "cloudflare",
    label: "Cloudflare 临时邮箱",
    description: "适合自建 Worker/API；可配置域名、鉴权方式和收信路径。",
  },
  {
    value: "duckmail",
    label: "DuckMail / Mail.tm",
    description: "通用临时邮箱接口；DuckMail 可填 API Key，Mail.tm 公共接口可留空。",
  },
  {
    value: "yyds",
    label: "YYDS 临时邮箱",
    description: "需要 YYDS API Key 或 JWT，可固定已验证收信域名。",
  },
  {
    value: "mailnest",
    label: "MailNest 迈巢 Outlook",
    description: "Outlook 临时邮箱服务，需要 API Key 和项目代码。",
  },
  {
    value: "outlookemail",
    label: "OutlookEmail 邮箱池",
    description: "支持外部 accounts 账号池或站内 temp 临时邮箱。",
  },
  {
    value: "cloudmail",
    label: "CloudMail 自建邮箱",
    description: "适合自建 cloud-mail，需要站点地址、管理员账号和域名。",
  },
];
const SETTINGS_SECTIONS = [
  { value: "basic", label: "基础注册", description: "服务商、代理、并发与浏览器" },
  { value: "cpa", label: "CPA / Auth", description: "Token、目录与远程入库" },
  { value: "providers", label: "邮箱服务", description: "各邮箱服务商的凭证" },
  { value: "outlook", label: "Outlook 邮箱池", description: "账号池、临时邮箱与停用" },
];
const TOKEN_MODES = [
  { value: "device_protocol", label: "协议 Device Flow" },
  { value: "device_browser", label: "浏览器 Device Flow" },
  { value: "auth_code", label: "授权码 Authorization Code" },
];
const OUTLOOK_SOURCES = [
  { value: "accounts", label: "外部账号池 accounts" },
  { value: "temp", label: "站内临时邮箱 temp" },
];
const OUTLOOK_PICK_MODES = [
  { value: "random", label: "随机选取" },
  { value: "sequential", label: "顺序选取" },
];
const CLOUDFLARE_AUTH_MODES = [
  { value: "none", label: "无需鉴权" },
  { value: "bearer", label: "Bearer Token" },
  { value: "x-api-key", label: "X-API-Key" },
  { value: "x-admin-auth", label: "管理员密码 X-Admin-Auth" },
  { value: "query-key", label: "URL 参数 key" },
];

function ToggleRow({
  title,
  description,
  checked,
  onCheckedChange,
}: {
  title: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
}) {
  return (
    <div className="flex min-h-16 items-center justify-between gap-4 rounded-xl border bg-muted/35 px-3 py-3 sm:px-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        {description ? <div className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</div> : null}
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} label={title} />
    </div>
  );
}

function SectionIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-primary">
      {children}
    </span>
  );
}

function ConfigField({
  config,
  onFieldChange,
  label,
  field,
  type = "text",
  placeholder = "",
  helper = "",
}: {
  config: Record<string, any>;
  onFieldChange: (key: string, value: any) => void;
  label: string;
  field: string;
  type?: string;
  placeholder?: string;
  helper?: string;
}) {
  return (
    <div className="min-w-0 space-y-2">
      <Label htmlFor={field}>{label}</Label>
      <Input
        id={field}
        type={type}
        inputMode={type === "number" ? "numeric" : undefined}
        autoComplete={type === "password" ? "new-password" : "off"}
        placeholder={placeholder}
        value={config[field] ?? ""}
        onChange={(event) =>
          onFieldChange(
            field,
            type === "number" && event.target.value !== ""
              ? Number(event.target.value)
              : event.target.value
          )
        }
      />
      {helper ? <p className="text-xs leading-5 text-muted-foreground">{helper}</p> : null}
    </div>
  );
}

export function SettingsPage() {
  const [config, setConfig] = useState<Record<string, any>>({});
  const [activeSection, setActiveSection] = useState("basic");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [configFileOpen, setConfigFileOpen] = useState(false);
  const [configFileLoading, setConfigFileLoading] = useState(false);
  const [configFile, setConfigFile] = useState<ConfigFileSnapshot | null>(null);
  const [configFileError, setConfigFileError] = useState("");
  const [showConfigSecrets, setShowConfigSecrets] = useState(true);
  const [sub2apiTesting, setSub2apiTesting] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone?: "default" | "success" | "error" }>({
    message: "",
  });

  const showToast = (message: string, tone: "default" | "success" | "error" = "default") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast({ message: "" }), 2200);
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getConfig();
      setConfig(data.config || {});
    } catch (err: any) {
      showToast(err.message || "加载配置失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!configFileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfigFileOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [configFileOpen]);

  const setField = (key: string, value: any) => {
    setConfig((previous) => ({ ...previous, [key]: value }));
  };
  const fieldState = { config, onFieldChange: setField };
  const selectedProvider = PROVIDERS.find(
    (item) => item.value === (config.email_provider || "cloudflare")
  ) || PROVIDERS[0];

  const onSave = async () => {
    setSaving(true);
    try {
      const data = await api.saveConfig(config);
      setConfig(data.config || config);
      showToast(`已保存 ${data.changed?.length || 0} 项配置`, "success");
    } catch (err: any) {
      showToast(err.message || "保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const onTestSub2API = async () => {
    setSub2apiTesting(true);
    try {
      // 测试读取的是服务端已保存的配置，先落库再测试，保证表单改动生效
      await api.saveConfig(config);
      const result = await api.testSub2API();
      showToast(`Sub2API 连接成功，共 ${result.group_count ?? result.groups?.length ?? 0} 个分组`, "success");
    } catch (err: any) {
      showToast(err.message || "Sub2API 连接失败", "error");
    } finally {
      setSub2apiTesting(false);
    }
  };

  const loadConfigFile = async () => {
    setConfigFileLoading(true);
    setConfigFileError("");
    try {
      const data = await api.getConfigFile();
      setConfigFile(data.file);
    } catch (err: any) {
      setConfigFileError(err.message || "读取配置失败");
    } finally {
      setConfigFileLoading(false);
    }
  };

  const openConfigFile = () => {
    setConfigFileOpen(true);
    setShowConfigSecrets(true);
    void loadConfigFile();
  };

  const displayedConfigContent = (() => {
    const content = String(configFile?.content || "");
    if (showConfigSecrets || !content) return content;
    try {
      const parsed = JSON.parse(content);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return content;
      for (const key of configFile?.sensitive_keys || []) {
        if (key in parsed && parsed[key] !== "" && parsed[key] !== null) parsed[key] = "********";
      }
      return JSON.stringify(parsed, null, 2);
    } catch {
      return content;
    }
  })();

  const copyConfigValue = async (value: string, label: string) => {
    const copied = await copyText(value);
    showToast(copied ? `已复制${label}` : `${label}复制失败`, copied ? "success" : "error");
  };

  return (
    <div className="space-y-5 sm:space-y-6">
      <PageHeader
        title="系统设置"
        description="按功能区分注册、入库与邮箱配置；修改只在保存后生效。"
        actions={
          <>
            <Button className="basis-full sm:basis-auto" variant="outline" onClick={openConfigFile}>
              <FileJson className="h-4 w-4" aria-hidden="true" />
              查看配置
            </Button>
            <Button variant="outline" onClick={load} disabled={loading || saving}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              重新加载
            </Button>
            <Button onClick={onSave} disabled={saving || loading}>
              <Save className="h-4 w-4" aria-hidden="true" />
              {saving ? "保存中…" : "保存配置"}
            </Button>
          </>
        }
      />

      <div className="grid items-start gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <Card className="lg:sticky lg:top-24">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">设置菜单</CardTitle>
            <CardDescription>选择要维护的功能区域</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-1">
            {SETTINGS_SECTIONS.map((section) => (
              <button
                key={section.value}
                type="button"
                onClick={() => setActiveSection(section.value)}
                className={`rounded-xl border px-3 py-3 text-left transition-colors ${
                  activeSection === section.value
                    ? "border-primary bg-primary/10 text-primary"
                    : "bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <div className="text-sm font-medium">{section.label}</div>
                <div className="mt-1 text-xs leading-5 opacity-80">{section.description}</div>
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-4">
        {activeSection === "basic" ? (
        <Card>
          <CardHeader className="flex-row items-start gap-3">
            <SectionIcon><Settings2 className="h-5 w-5" aria-hidden="true" /></SectionIcon>
            <div>
              <CardTitle>基础与注册</CardTitle>
              <CardDescription>邮箱来源、代理、数量、并发和浏览器运行方式。</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="email_provider">邮箱服务商</Label>
              <Select
                id="email_provider"
                value={config.email_provider || "cloudflare"}
                onChange={(event) => setField("email_provider", event.target.value)}
              >
                {PROVIDERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </Select>
              <p className="text-xs leading-5 text-muted-foreground">{selectedProvider.description}</p>
            </div>
            <ConfigField
              {...fieldState}
              label="网络代理"
              field="proxy"
              placeholder="socks5://username:password@host:port"
              helper="支持 http://host:port、https://host:port、socks5://username:password@host:port，以及 host:port@username:password。用户名或密码含特殊字符时请先进行 URL 编码。"
            />
            <ConfigField {...fieldState}
              label="账号间隔（秒）"
              field="account_interval"
              placeholder="60-120"
              helper="支持固定秒数或区间；等待过程可随时停止。"
            />
            <ConfigField {...fieldState} label="注册数量" field="register_count" type="number" />
            <ConfigField {...fieldState} label="并发浏览器数" field="register_workers" type="number" />
            <ConfigField {...fieldState} label="日志级别" field="log_level" placeholder="info（普通）/ debug（详细）" />
            <div className="min-w-0 space-y-2">
              <Label htmlFor="browser_locale">浏览器界面语言</Label>
              <Select
                id="browser_locale"
                value={config.browser_locale || "en-US"}
                onChange={(event) => setField("browser_locale", event.target.value)}
              >
                <option value="en-US">English (en-US，推荐)</option>
                <option value="zh-CN">简体中文 (zh-CN)</option>
              </Select>
              <p className="text-xs leading-5 text-muted-foreground">
                固定注册页面语言，不跟随代理出口自动切换。
              </p>
            </div>
            <div className="space-y-3 sm:col-span-2">
              <ToggleRow
                title="注册后开启 NSFW"
                description="失败时不阻塞账号保存与 CPA 入库"
                checked={!!config.enable_nsfw}
                onCheckedChange={(value) => setField("enable_nsfw", value)}
              />
              <ToggleRow
                title="调试模式"
                description="强制单账号，结束后保留浏览器"
                checked={!!config.debug_mode}
                onCheckedChange={(value) => setField("debug_mode", value)}
              />
              <ToggleRow
                title="无头浏览器"
                description="后台运行且不显示窗口；Camoufox 会修正常见无头指纹，但无法保证不触发站点风控"
                checked={!!config.browser_headless}
                onCheckedChange={(value) => setField("browser_headless", value)}
              />
              <ToggleRow
                title="停止时关闭浏览器"
                description="收到停止请求后清理当前浏览器实例"
                checked={!!config.close_browser_on_stop}
                onCheckedChange={(value) => setField("close_browser_on_stop", value)}
              />
            </div>
          </CardContent>
        </Card>
        ) : null}

        {activeSection === "cpa" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-start gap-3">
              <SectionIcon><ShieldCheck className="h-5 w-5" aria-hidden="true" /></SectionIcon>
              <div>
                <CardTitle>授权转换</CardTitle>
                <CardDescription>注册完成后将 SSO 换为 CPA 与 Grok2API 所需凭据。</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <ToggleRow
                  title="注册后自动 SSO → auth"
                  description="所有邮箱服务商都必须 CPA 状态为 success 才计注册成功，请保持开启"
                  checked={!!config.cpa_auto_add}
                  onCheckedChange={(value) => setField("cpa_auto_add", value)}
                />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="cpa_token_mode">授权转换方式</Label>
                <Select
                  id="cpa_token_mode"
                  value={config.cpa_token_mode || "device_protocol"}
                  onChange={(event) => setField("cpa_token_mode", event.target.value)}
                >
                  {TOKEN_MODES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </Select>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>CPA 目标</CardTitle>
                <CardDescription>保存本地 CPA JSON，也可上传到远程 Management API。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                <ConfigField {...fieldState} label="本地授权目录" field="cpa_auth_dir" />
                <ConfigField {...fieldState} label="远程 CPA 地址" field="cpa_remote_url" placeholder="http://host:8317" />
                <ConfigField {...fieldState} label="远程管理密钥" field="cpa_management_key" type="password" />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Grok2API 目标</CardTitle>
                <CardDescription>保存 grok_build JSON，并通过管理员账号登录远程服务导入。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                <ConfigField {...fieldState} label="本地授权目录" field="grok2api_auth_dir" />
                <ConfigField
                  {...fieldState}
                  label="远程 API 地址"
                  field="grok2api_remote_url"
                  placeholder="https://api.example.com"
                  helper="填写站点根地址，不要附加 /api/admin/v1"
                />
                <ConfigField {...fieldState} label="管理员账号" field="grok2api_remote_username" />
                <ConfigField {...fieldState} label="管理员密码" field="grok2api_remote_password" type="password" />
                <ToggleRow
                  title="转换成功后自动导入"
                  description="生成 Grok2API JSON 后立即登录远程管理端并导入；导入结果单独记录"
                  checked={!!config.grok2api_auto_import}
                  onCheckedChange={(value) => setField("grok2api_auto_import", value)}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Sub2API 目标</CardTitle>
                <CardDescription>通过管理员邮箱登录 sub2api，按名称幂等导入 grok/oauth 账号。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                <ConfigField
                  {...fieldState}
                  label="远程 API 地址"
                  field="sub2api_remote_url"
                  placeholder="https://sub2api.example.com"
                  helper="填写站点根地址，不要附加 /api/v1"
                />
                <ConfigField {...fieldState} label="管理员邮箱" field="sub2api_remote_email" placeholder="admin@example.com" />
                <ConfigField {...fieldState} label="管理员密码" field="sub2api_remote_password" type="password" />
                <div className="grid gap-4 sm:grid-cols-2">
                  <ConfigField
                    {...fieldState}
                    label="分组名称"
                    field="sub2api_group_name"
                    helper="留空使用 grok-register"
                  />
                  <ConfigField
                    {...fieldState}
                    label="分组 ID"
                    field="sub2api_group_id"
                    type="number"
                    helper="填 0 按名称匹配或自动创建"
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <ConfigField {...fieldState} label="每账号并发" field="sub2api_account_concurrency" type="number" />
                  <ConfigField {...fieldState} label="每账号优先级" field="sub2api_account_priority" type="number" />
                </div>
                <ToggleRow
                  title="转换成功后自动导入"
                  description="SSO 换 token 成功后立即推送到 Sub2API；同名账号自动刷新凭据，导入结果单独记录"
                  checked={!!config.sub2api_auto_import}
                  onCheckedChange={(value) => setField("sub2api_auto_import", value)}
                />
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void onTestSub2API()}
                    disabled={sub2apiTesting}
                  >
                    {sub2apiTesting ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <UploadCloud className="h-4 w-4" aria-hidden="true" />
                    )}
                    {sub2apiTesting ? "正在测试连接" : "测试连接"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
        ) : null}

        {activeSection === "providers" ? (
        <Card>
          <CardHeader className="flex-row items-start gap-3">
            <SectionIcon><Cloud className="h-5 w-5" aria-hidden="true" /></SectionIcon>
            <div>
              <CardTitle>邮箱服务商凭证</CardTitle>
              <CardDescription>当前选择：{selectedProvider.label}。这里只显示该服务所需字段。</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2 rounded-xl border bg-muted/35 p-3 text-sm">
              <div className="font-medium">{selectedProvider.label}</div>
              <div className="mt-1 text-xs leading-5 text-muted-foreground">{selectedProvider.description}</div>
            </div>

            {selectedProvider.value === "duckmail" ? (
              <>
                <ConfigField {...fieldState} label="接口地址" field="duckmail_api_base" helper="DuckMail 默认 https://api.duckmail.sbs；Mail.tm 填 https://api.mail.tm" />
                <ConfigField {...fieldState} label="API Key" field="duckmail_api_key" type="password" helper="DuckMail 私有域需要；Mail.tm 公共接口可留空" />
              </>
            ) : null}

            {selectedProvider.value === "cloudflare" ? (
              <>
                <ConfigField {...fieldState} label="接口地址" field="cloudflare_api_base" helper="Cloudflare 临时邮箱 Worker/API 根地址" />
                <ConfigField {...fieldState} label="API Key / 管理员密码" field="cloudflare_api_key" type="password" />
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="cloudflare_auth_mode">鉴权方式</Label>
                  <Select
                    id="cloudflare_auth_mode"
                    value={config.cloudflare_auth_mode || "none"}
                    onChange={(event) => setField("cloudflare_auth_mode", event.target.value)}
                  >
                    {CLOUDFLARE_AUTH_MODES.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </Select>
                </div>
                <ConfigField {...fieldState} label="全局访问密码" field="cloudflare_custom_auth" type="password" helper="对应 Worker PASSWORDS，发送到 X-Custom-Auth" />
                <ConfigField {...fieldState} label="收信域名" field="defaultDomains" helper="多个域名可用逗号或空格分隔" />
                <ConfigField {...fieldState} label="域名接口路径" field="cloudflare_path_domains" />
                <ConfigField {...fieldState} label="创建邮箱接口路径" field="cloudflare_path_accounts" />
                <ConfigField {...fieldState} label="获取 Token 接口路径" field="cloudflare_path_token" />
                <ConfigField {...fieldState} label="邮件列表接口路径" field="cloudflare_path_messages" />
              </>
            ) : null}

            {selectedProvider.value === "yyds" ? (
              <>
                <ConfigField {...fieldState} label="API Key" field="yyds_api_key" type="password" helper="API Key 与 JWT 至少填写一个" />
                <ConfigField {...fieldState} label="JWT" field="yyds_jwt" type="password" helper="填写 JWT 时优先使用 JWT 鉴权" />
                <ConfigField {...fieldState} label="固定收信域名" field="yyds_default_domain" helper="留空时自动选择已验证域名" />
              </>
            ) : null}

            {selectedProvider.value === "mailnest" ? (
              <>
                <ConfigField {...fieldState} label="API Key" field="mailnest_api_key" type="password" />
                <ConfigField {...fieldState} label="项目代码" field="mailnest_project_code" helper="默认 x-ai001" />
              </>
            ) : null}

            {selectedProvider.value === "cloudmail" ? (
              <>
                <ConfigField {...fieldState} label="站点地址" field="cloudmail_url" helper="自建 cloud-mail 根地址，不要附加 /api" />
                <ConfigField {...fieldState} label="管理员邮箱" field="cloudmail_admin_email" />
                <ConfigField {...fieldState} label="管理员密码" field="cloudmail_password" type="password" />
                <ConfigField {...fieldState} label="收信域名" field="defaultDomains" helper="多个域名可用逗号或空格分隔" />
              </>
            ) : null}

            {selectedProvider.value === "outlookemail" ? (
              <div className="sm:col-span-2 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
                OutlookEmail 的账号池、临时邮箱和自动停用配置已单独放在“Outlook 邮箱池”子菜单。
              </div>
            ) : null}
          </CardContent>
        </Card>
        ) : null}

        {activeSection === "outlook" ? (
        <Card>
          <CardHeader className="flex-row items-start gap-3">
            <SectionIcon><Mail className="h-5 w-5" aria-hidden="true" /></SectionIcon>
            <div>
              <CardTitle>OutlookEmail 邮箱池</CardTitle>
              <CardDescription>接口、分组、选取方式与 Web 会话配置。</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <ToggleRow
                title="CPA 成功后停用 Outlook 邮箱"
                description="仅 accounts 来源生效；CPA 状态必须为 success，随后自动更新邮箱为 inactive"
                checked={!!config.outlookemail_disable_after_cpa_success}
                onCheckedChange={(value) =>
                  setField("outlookemail_disable_after_cpa_success", value)
                }
              />
            </div>
            <ConfigField {...fieldState}
              label="API Base"
              field="outlookemail_api_base"
              helper="Compose 可选服务使用 http://outlook-email:5000；外部服务填写其实际地址"
            />
            <ConfigField {...fieldState}
              label="API Key"
              field="outlookemail_api_key"
              type="password"
              helper="accounts 来源读取账号列表和邮件时使用"
            />
            <div className="min-w-0 space-y-2">
              <Label htmlFor="outlookemail_source">邮箱来源</Label>
              <Select
                id="outlookemail_source"
                value={config.outlookemail_source || "accounts"}
                onChange={(event) => setField("outlookemail_source", event.target.value)}
              >
                {OUTLOOK_SOURCES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </Select>
              <p className="text-xs leading-5 text-muted-foreground">
                自动停用接口仅适用于 accounts 来源。
              </p>
            </div>
            <ConfigField {...fieldState} label="分组 ID" field="outlookemail_group_id" />
            <div className="min-w-0 space-y-2">
              <Label htmlFor="outlookemail_pick_mode">邮箱选取方式</Label>
              <Select
                id="outlookemail_pick_mode"
                value={config.outlookemail_pick_mode || "random"}
                onChange={(event) => setField("outlookemail_pick_mode", event.target.value)}
              >
                {OUTLOOK_PICK_MODES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </Select>
            </div>
            <ConfigField {...fieldState} label="邮件文件夹" field="outlookemail_folder" helper="accounts 来源拉取邮件的文件夹，默认 all" />
            <ConfigField {...fieldState} label="单次拉取邮件数" field="outlookemail_top" type="number" />
            <ConfigField {...fieldState} label="临时邮箱标签 ID" field="outlookemail_temp_tag_ids" helper="仅 temp 来源使用，多个 ID 用逗号分隔" />
            <ConfigField {...fieldState}
              label="管理网页登录密码"
              field="outlookemail_web_password"
              type="password"
              helper="保存后会自动登录、获取 Session Cookie 与 CSRF Token，无需手工抓取"
            />
            <ConfigField {...fieldState}
              label="Session Cookie（兼容回退）"
              field="outlookemail_session_cookie"
              type="password"
              helper="填写管理密码后可留空；仅用于没有密码时兼容已有配置"
            />
          </CardContent>
        </Card>
        ) : null}
        </div>
      </div>

      <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-20 rounded-2xl border bg-card/95 p-2 shadow-lg backdrop-blur lg:hidden">
        <Button className="w-full" onClick={onSave} disabled={saving || loading}>
          <Save className="h-4 w-4" aria-hidden="true" />
          {saving ? "保存中…" : "保存全部配置"}
        </Button>
      </div>

      {configFileOpen ? (
        <div
          className="fixed inset-0 z-[70] flex items-end bg-slate-950/50 sm:items-center sm:justify-center sm:p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setConfigFileOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="config-file-title"
            className="flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-card shadow-2xl sm:max-w-5xl sm:rounded-3xl"
          >
            <div className="mx-auto mt-2 h-1.5 w-12 shrink-0 rounded-full bg-slate-300 sm:hidden" />
            <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
              <div className="min-w-0">
                <h2 id="config-file-title" className="flex items-center gap-2 font-semibold text-foreground">
                  <FileJson className="h-4 w-4 text-primary" aria-hidden="true" />
                  配置详情
                </h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {configFile?.exists ? "磁盘文件" : "运行时配置预览"}
                </p>
              </div>
              <Button size="icon" variant="ghost" onClick={() => setConfigFileOpen(false)} aria-label="关闭配置详情">
                <X className="h-5 w-5" aria-hidden="true" />
              </Button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
              {configFileLoading && !configFile ? (
                <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  读取中…
                </div>
              ) : configFileError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{configFileError}</div>
              ) : configFile ? (
                <div className="space-y-4">
                  <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-center">
                    <div className="min-w-0 rounded-xl border bg-muted/35 p-3">
                      <div className="text-xs font-medium text-muted-foreground">实际路径</div>
                      <div className="mt-1 break-all font-mono text-xs leading-5 text-foreground">{configFile.path}</div>
                    </div>
                    <Button variant="outline" onClick={() => copyConfigValue(configFile.path, "配置路径")}>
                      <Copy className="h-4 w-4" aria-hidden="true" />
                      复制路径
                    </Button>
                    <Button variant="outline" onClick={loadConfigFile} disabled={configFileLoading}>
                      <RefreshCw className={`h-4 w-4 ${configFileLoading ? "animate-spin" : ""}`} aria-hidden="true" />
                      刷新
                    </Button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className={`rounded-full border px-2.5 py-1 ${configFile.exists ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "bg-muted"}`}>
                      {configFile.exists ? "文件存在" : "文件未创建"}
                    </span>
                    <span>{configFile.size.toLocaleString()} bytes</span>
                    {configFile.modified_at ? <span>{new Date(configFile.modified_at).toLocaleString()}</span> : null}
                  </div>

                  {configFile.parse_error ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                      JSON 解析异常：{configFile.parse_error}
                    </div>
                  ) : null}

                  <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-slate-800">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white/80 px-3 py-2">
                      <span className="text-xs font-medium text-slate-600">JSON 配置内容</span>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setShowConfigSecrets((value) => !value)}
                        >
                          {showConfigSecrets ? <EyeOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Eye className="h-3.5 w-3.5" aria-hidden="true" />}
                          {showConfigSecrets ? "隐藏敏感值" : "显示敏感值"}
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => copyConfigValue(displayedConfigContent, "JSON")}>
                          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                          复制 JSON
                        </Button>
                      </div>
                    </div>
                    <pre className="max-h-[52dvh] overflow-auto whitespace-pre p-4 font-mono text-xs leading-5 sm:text-sm">
                      {displayedConfigContent}
                    </pre>
                  </div>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      <Toast message={toast.message} tone={toast.tone} />
    </div>
  );
}
