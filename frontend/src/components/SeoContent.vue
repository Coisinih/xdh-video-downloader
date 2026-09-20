<script setup lang="ts">
import {
  BrainCircuit,
  Captions,
  CheckCircle2,
  Download,
  FileText,
  GitBranch,
  Globe2,
  Link2,
  MessageCircleQuestion,
  ShieldCheck,
} from 'lucide-vue-next'
</script>

<template>
  <div class="seo-content">
    <section class="answer-block content-section" aria-labelledby="what-is-vidnest">
      <div>
        <p class="section-kicker">产品定义</p>
        <h2 id="what-is-vidnest">VidNest 是什么？</h2>
      </div>
      <p>
        VidNest 是一款面向公开网络视频的在线下载与 AI 总结工具。用户粘贴有权保存的视频链接后，可以解析视频信息、选择可用清晰度并下载；当视频提供字幕时，还可以查看字幕、生成视频大纲与思维导图，并基于字幕证据进行问答。
      </p>
    </section>

    <section id="features" class="content-section" aria-labelledby="features-title">
      <header class="section-heading">
        <p class="section-kicker">核心功能</p>
        <h2 id="features-title">从视频下载到内容理解，一处完成</h2>
        <p>VidNest 将公开视频解析、清晰度选择、字幕提取和 AI 视频总结组合在同一个浏览器工作台中。</p>
      </header>
      <div class="feature-grid">
        <article class="feature-card">
          <span class="feature-icon"><Download :size="23" aria-hidden="true" /></span>
          <h3>在线视频下载</h3>
          <p>解析公开视频元数据和可用格式，按来源实际提供的清晰度选择 MP4 等格式并下载。</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon"><Captions :size="23" aria-hidden="true" /></span>
          <h3>字幕提取与导出</h3>
          <p>优先读取视频已有字幕，展示带时间戳的字幕内容，并支持导出 UTF-8 SRT 或 TXT 文件。</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon"><BrainCircuit :size="23" aria-hidden="true" /></span>
          <h3>AI 视频总结</h3>
          <p>根据字幕生成视频大纲、核心知识点和关键词，不上传视频音频，也不执行音频转写。</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon"><GitBranch :size="23" aria-hidden="true" /></span>
          <h3>思维导图与问答</h3>
          <p>把内容组织为可缩放思维导图，并通过带字幕时间范围引用的回答帮助核验信息来源。</p>
        </article>
      </div>
    </section>

    <section id="how-it-works" class="content-section process-section" aria-labelledby="process-title">
      <header class="section-heading">
        <p class="section-kicker">使用方法</p>
        <h2 id="process-title">三步下载并总结公开视频</h2>
      </header>
      <ol class="process-list">
        <li>
          <span>1</span>
          <div><h3>粘贴公开视频链接</h3><p>输入 HTTP 或 HTTPS 视频页面地址，VidNest 会先校验链接并解析公开元数据。</p></div>
        </li>
        <li>
          <span>2</span>
          <div><h3>选择可用清晰度</h3><p>查看标题、封面、作者和格式，根据来源实际提供的 1080P、720P、480P 或 360P 选项进行选择。</p></div>
        </li>
        <li>
          <span>3</span>
          <div><h3>下载或生成 AI 总结</h3><p>直接保存视频；如果检测到可用字幕，还可继续生成大纲、思维导图和字幕证据问答。</p></div>
        </li>
      </ol>
    </section>

    <section id="platforms" class="content-section" aria-labelledby="platforms-title">
      <header class="section-heading">
        <p class="section-kicker">平台支持</p>
        <h2 id="platforms-title">已验证的公开视频来源</h2>
        <p>平台策略会持续变化，是否可用以具体公开作品、网络环境和来源平台当前规则为准。</p>
      </header>
      <div class="platform-grid">
        <article><CheckCircle2 :size="20" aria-hidden="true" /><div><h3>Bilibili（B 站）</h3><p>已验证公开视频解析、元数据补全与下载链路。</p></div></article>
        <article><CheckCircle2 :size="20" aria-hidden="true" /><div><h3>AcFun</h3><p>已验证公开作品解析及 MP4 媒体下载。</p></div></article>
        <article><CheckCircle2 :size="20" aria-hidden="true" /><div><h3>虎牙视频</h3><p>已验证公开作品解析及 MP4 媒体下载。</p></div></article>
        <article class="conditional"><Globe2 :size="20" aria-hidden="true" /><div><h3>其他公开视频源</h3><p>可尝试解析；需要登录、Cookie、验证码、付费授权或 DRM 的内容不受支持。</p></div></article>
      </div>
    </section>

    <section class="content-section facts-section" aria-labelledby="facts-title">
      <header class="section-heading">
        <p class="section-kicker">可核验事实</p>
        <h2 id="facts-title">VidNest 产品信息</h2>
      </header>
      <dl class="facts-list">
        <div><dt>产品类型</dt><dd>浏览器端公开视频下载与 AI 视频学习工具</dd></div>
        <div><dt>核心能力</dt><dd>视频解析、格式选择、视频下载、字幕导出、AI 大纲、思维导图、字幕证据问答</dd></div>
        <div><dt>AI 内容来源</dt><dd>视频来源方已经提供的字幕；VidNest 不上传视频音频，也不执行 ASR 音频转写</dd></div>
        <div><dt>已验证平台</dt><dd>Bilibili、AcFun、虎牙视频的公开样本</dd></div>
        <div><dt>数据保留</dt><dd>任务、总结和临时文件仅短期保存在内存或临时目录，默认约 2 小时后清理</dd></div>
        <div><dt>产品主体</dt><dd>VidNest；开发者：咸蛋黄；联系邮箱：senwei0521@gmail.com</dd></div>
        <div><dt>信息更新时间</dt><dd><time datetime="2026-09-20">2026 年 9 月 20 日</time></dd></div>
      </dl>
    </section>

    <section class="content-section compliance-section" aria-labelledby="compliance-title">
      <span class="compliance-icon"><ShieldCheck :size="28" aria-hidden="true" /></span>
      <div>
        <p class="section-kicker">合规与安全边界</p>
        <h2 id="compliance-title">只处理用户有权保存的公开内容</h2>
        <p>VidNest 不接收用户 Cookie，不绕过验证码、登录、付费授权、平台访问控制或 DRM。用户应确认自己拥有保存和使用内容的权利，并遵守来源平台规则及所在地法律。</p>
      </div>
    </section>

    <section id="faq" class="content-section" aria-labelledby="faq-title">
      <header class="section-heading">
        <p class="section-kicker">常见问题</p>
        <h2 id="faq-title">关于视频下载与 AI 总结</h2>
      </header>
      <div class="faq-list">
        <details>
          <summary>VidNest 可以下载哪些视频？</summary>
          <p>VidNest 仅处理公开、无 DRM、无需登录或 Cookie 的视频。私密视频、付费内容、需要验证码或登录授权的内容不在支持范围内。</p>
        </details>
        <details>
          <summary>目前支持哪些视频平台？</summary>
          <p>当前已使用公开样本验证 Bilibili、AcFun 和虎牙视频。其他来源可以尝试解析，但平台策略和具体作品状态会影响结果，因此不承诺所有链接始终可用。</p>
        </details>
        <details>
          <summary>AI 视频总结需要什么条件？</summary>
          <p>视频必须提供 VidNest 能读取的字幕轨道，并且部署环境已配置 AI 模型服务。没有字幕时仍可使用正常的视频解析和下载功能。</p>
        </details>
        <details>
          <summary>VidNest 会上传视频或保存长期历史吗？</summary>
          <p>不会上传视频音频用于转写。当前版本没有账号、数据库或持久历史；解析任务、AI 总结和临时下载文件默认约 2 小时后清理。</p>
        </details>
        <details>
          <summary>使用 VidNest 下载视频是否合法？</summary>
          <p>是否合法取决于内容授权、来源平台规则和当地法律。VidNest 只提供处理公开媒体的技术工具，用户必须确保自己有权保存和使用相关内容。</p>
        </details>
        <details>
          <summary>VidNest 当前是否需要注册或付费？</summary>
          <p>当前版本无需注册账号，也没有支付功能。实际部署方仍可根据服务器资源设置文件大小、并发量或使用频率限制。</p>
        </details>
      </div>
    </section>

    <section id="about" class="content-section about-section" aria-labelledby="about-title">
      <div class="about-copy">
        <p class="section-kicker">关于项目</p>
        <h2 id="about-title">由开发者咸蛋黄维护的 VidNest</h2>
        <p>如果你发现平台兼容性问题、需要反馈公开样本，或对 VidNest 的视频下载与 AI 总结能力有建议，可以通过邮箱联系开发者。</p>
      </div>
      <a class="contact-card" href="mailto:senwei0521@gmail.com">
        <MessageCircleQuestion :size="22" aria-hidden="true" />
        <span><small>联系邮箱</small><strong>senwei0521@gmail.com</strong></span>
      </a>
    </section>

    <aside class="source-note" aria-label="信息来源说明">
      <FileText :size="18" aria-hidden="true" />
      <p>本页产品能力、支持边界和数据保留说明来自 VidNest 项目需求、架构与平台验证记录。平台兼容性会随来源规则变化而调整。</p>
      <a href="#main-content"><Link2 :size="15" aria-hidden="true" />返回下载工具</a>
    </aside>
  </div>
</template>
