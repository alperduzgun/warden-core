class Warden < Formula
  include Language::Python::Virtualenv

  desc "AI Code Guardian for comprehensive code validation"
  homepage "https://github.com/alperduzgun/warden-core"
  
  # Stable Release (Update this section when releasing a new version)
  url "https://github.com/alperduzgun/warden-core/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256"
  
  # Development Head
  head "https://github.com/alperduzgun/warden-core.git", branch: "main"

  license "Proprietary"

  depends_on "python@3.11"

  def install
    # Create virtualenv in libexec
    virtualenv_create(libexec, "python3.11")
    
    # Install with absolute path
    system libexec/"bin/pip", "install", "-v", Dir.pwd
    
    # Link the binary
    bin.install_symlink libexec/"bin/warden"
  end

  test do
    system "#{bin}/warden", "--help"
  end
end
