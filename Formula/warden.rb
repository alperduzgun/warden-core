# Warden Core Homebrew Formula
# This file allows installing Warden via Homebrew
# Usage: brew install --HEAD ./Formula/warden.rb

class Warden < Formula
  include Language::Python::Virtualenv

  desc "AI Code Guardian - Secure your code before production"
  homepage "https://github.com/yourusername/warden-core"
  url "https://github.com/yourusername/warden-core.git", branch: "main"
  version "0.1.0"
  head "https://github.com/yourusername/warden-core.git", branch: "main"

  depends_on "python@3.11"
  depends_on "node" => :optional # For the interactive CLI

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/warden", "version"
  end
end
