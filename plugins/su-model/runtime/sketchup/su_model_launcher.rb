# -*- coding: utf-8 -*-
# su_model_launcher.rb — SketchUp AI 建模「一键启动」插件
#
# 用途：一键启动 su-mcp 的后端建模服务（su_server.rb，监听 127.0.0.1:45678），
# 让 Codex 的 su-mcp 工具就能直接驱动 SketchUp 建模；并提供停止/状态/截图。
#
# 安装：运行仓库 scripts/install-bridges.ps1 -Target SketchUp，显式指定 Plugins 目录。
# 启动器放在 Plugins 根目录；服务保存在 su_model_runtime 子目录，防止自动重复加载。
# 公开版工具栏图标为可选资源；没有图标时保留文字菜单和按钮。

require "sketchup.rb"

module SuModelLauncher
  PACKAGED_SERVER = File.join(__dir__, "su_model_runtime", "su_server.rb")
  SERVER_RB = ENV["SU_MODEL_SERVER"] || (File.file?(PACKAGED_SERVER) ? PACKAGED_SERVER : File.join(__dir__, "su_server.rb"))
  ICON_DIR = File.join(__dir__, "su_model_runtime", "icons")
  PORT = 45678

  def self.icon(name)
    File.join(ICON_DIR, name).tr("\\", "/")
  end

  # 当前建模服务是否已在运行（以 TCP 监听状态为准，比“是否已 load”更准）
  def self.running?
    defined?(Su) && Su.respond_to?(:server) && Su.server && !Su.server.closed?
  end

  def self.start(show_msg = true)
    if running?
      UI.messagebox("AI 建模服务已在运行（127.0.0.1:#{PORT}）") if show_msg
      return true
    end
    unless File.exist?(SERVER_RB)
      UI.messagebox("未找到建模脚本：\n#{SERVER_RB}") if show_msg
      return false
    end
    load SERVER_RB
    ok = running?
    apply_precision if ok
    UI.messagebox(ok ? "✅ AI 建模服务已启动（127.0.0.1:#{PORT}）。现在可以用 Codex 建模了。" : "启动似乎失败，请查看 Ruby Console 输出。") if show_msg
    ok
  rescue => e
    UI.messagebox("启动 AI 建模服务失败：#{e.class}: #{e.message}") if show_msg
    false
  end

  # 默认精度：毫米 + 3 位（不打扰，静默应用）
  def self.apply_precision(unit = :mm, prec = 3)
    Su.set_units(unit, prec) if defined?(Su) && Su.respond_to?(:set_units)
  end

  def self.set_units(unit = :mm, prec = 3)
    return UI.messagebox("建模服务未就绪，请先点「一键启动」") unless defined?(Su) && Su.respond_to?(:set_units)
    Su.set_units(unit, prec)
    UI.messagebox("已设为 #{unit} / #{prec} 位精度")
  end

  def self.measure
    return UI.messagebox("建模服务未就绪，请先点「一键启动」") unless defined?(Su) && Su.respond_to?(:bounds)
    UI.messagebox(Su.bounds(nil, nil))
  end

  def self.stop(show_msg = true)
    if running?
      Su.stop_server
      UI.messagebox("AI 建模服务已停止") if show_msg
    else
      UI.messagebox("建模服务当前未运行") if show_msg
    end
  end

  def self.status
    m = Sketchup.active_model
    lines = []
    lines << (running? ? "建模服务：运行中（127.0.0.1:#{PORT}）" : "建模服务：未运行")
    lines << (m.nil? ? "模型：未打开（请 文件→新建）" : "模型：#{m.title}（#{m.entities.count} 个实体）")
    UI.messagebox(lines.join("\n"))
  end

  def self.screenshot
    return UI.messagebox("建模服务未就绪，请先点「一键启动」") unless running?
    return UI.messagebox("没有打开的模型，请先 文件→新建") if Sketchup.active_model.nil?
    path = File.join(Dir.home, "Desktop", "su_feedback_#{Time.now.strftime('%Y%m%d_%H%M%S')}.png")
    begin
      Sketchup.active_model.active_view.write_image(path, 1600, 900, true, 0.9)
      UI.messagebox("已截图：#{path}\n（可在 Codex 里让我读取并继续建模）")
    rescue => e
      UI.messagebox("截图失败：#{e.class}: #{e.message}")
    end
  end

  # 建一个工具栏命令
  def self.cmd(name_short, tooltip, icon, &blk)
    c = UI::Command.new(name_short) { blk.call }
    icon_path = icon(icon)
    if File.file?(icon_path)
      c.small_icon = icon_path
      c.large_icon = icon_path
    end
    c.tooltip = tooltip
    c.status_bar_text = tooltip
    c
  end

  def self.build_ui
    unless file_loaded?(__FILE__)
      # 菜单
      menu = UI.menu("Extensions").add_submenu("SU AI 建模")
      menu.add_item("一键启动 AI 建模") { start(true) }
      menu.add_item("停止建模服务") { stop(true) }
      menu.add_item("状态检测") { status }
      menu.add_item("截图给 Codex") { screenshot }
      menu.add_separator
      um = menu.add_submenu("单位 / 精度")
      um.add_item("毫米 / 3 位") { set_units(:mm, 3) }
      um.add_item("厘米 / 3 位") { set_units(:cm, 3) }
      um.add_item("米 / 3 位") { set_units(:m, 3) }
      um.add_item("英寸 / 3 位") { set_units(:in, 3) }
      um.add_separator
      um.add_item("量取整体尺寸") { measure }
      menu.add_item("量取整体尺寸") { measure }
      # 工具栏（一键启动）
      tb = UI::Toolbar.new("SU AI 建模")
      tb.add_item(cmd("一键启动", "启动 AI 建模服务（供 Codex 驱动建模）", "su_ai_start.png") { start(true) })
      tb.add_item(cmd("停止", "停止建模服务", "su_ai_stop.png") { stop(true) })
      tb.add_item(cmd("状态", "检测建模服务与模型状态", "su_ai_ping.png") { status })
      tb.add_item(cmd("截图", "导出当前视图给 Codex 读取", "su_ai_shot.png") { screenshot })
      tb.add_item(cmd("量取", "量取整体尺寸（精度核对）", "su_ai_ping.png") { measure })
      tb.add_item(cmd("毫米", "单位设为毫米/3位", "su_ai_shot.png") { set_units(:mm, 3) })
      tb.restore
      tb.show
      file_loaded(__FILE__)
    end
  end
end

SuModelLauncher.build_ui

# 启动时静默尝试自动拉起建模服务（延迟到 UI 就绪；端口占用则跳过）
UI.start_timer(0.6, false) { SuModelLauncher.start(false) }
