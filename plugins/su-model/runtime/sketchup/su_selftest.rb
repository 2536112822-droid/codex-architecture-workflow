# -*- coding: utf-8 -*-
# su_selftest.rb — SketchUp Ruby 控制台直接 load 本文件即可自检建模能力。
# 用法：load "C:/path/to/repository/plugins/su-model/runtime/sketchup/su_selftest.rb"
begin
  server_path = File.join(File.dirname(__FILE__), "su_server.rb")
  load server_path unless defined?(Su) && Su.respond_to?(:selftest)
rescue => e
  puts "加载 su_server.rb 失败: #{e.class}: #{e.message}"
end
begin
  puts(defined?(Su) && Su.respond_to?(:selftest) ? Su.selftest : "尚未定义 Su.selftest，请确认已加载新版 su_server.rb")
rescue => e
  puts "自检异常: #{e.class}: #{e.message}"
end
