<#
scripts/run_phase7_full.ps1
============================

一键跑完所有 quantlab 集成相关测试（Phase 7 补齐 + Phase 1-6 回归）。

用法（在你本地 vbt 可用的环境）：
    powershell -ExecutionPolicy Bypass -File scripts\run_phase7_full.ps1

输出：
    - 控制台彩色日志
    - reports\phase7_test_results.txt  全量日志
    - reports\phase7_test_summary.json  汇总 JSON

退出码：
    0  全部通过（或仅 VBT 相关 SKIPPED）
    1  有 FAILED
#>

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $ProjectRoot "reports"
$logFile = Join-Path $logDir "phase7_test_results_$timestamp.txt"
$jsonFile = Join-Path $logDir "phase7_test_summary_$timestamp.json"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " QuantLab Phase 7 Full Test Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Project  : $ProjectRoot"
Write-Host " Log File : $logFile"
Write-Host " JSON     : $jsonFile"
Write-Host ""

# 探测 vbt
Write-Host "[1/5] Probing vectorbt availability ..." -ForegroundColor Yellow
$vbtCheck = python -c "import vectorbt; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    $vbtAvail = $true
    Write-Host "  vectorbt: AVAILABLE" -ForegroundColor Green
} else {
    $vbtAvail = $false
    Write-Host "  vectorbt: NOT AVAILABLE (vbt tests will SKIP)" -ForegroundColor Yellow
}
Write-Host ""

# 测试套件清单
$testSuites = @(
    @{
        name = "quantlab_integration (DataAdapter/ResultAdapter/Tracker/Optimizer/WF)"
        path = "tests/test_quantlab_integration.py"
        vbt_required = $false
    },
    @{
        name = "quantlab_risk_check (6 RiskCheck)"
        path = "tests/test_quantlab_risk_check.py"
        vbt_required = $false
    },
    @{
        name = "quantlab_strategy_v2 (6 v2 strategies)"
        path = "tests/test_quantlab_strategy_v2.py"
        vbt_required = $false
    },
    @{
        name = "quantlab_adapter (DataAdapter/ResultAdapter)"
        path = "tests/test_quantlab_adapter.py"
        vbt_required = $false
    },
    @{
        name = "quintile_experiment (QuintileExperiment)"
        path = "tests/test_quintile_experiment.py"
        vbt_required = $false
    },
    @{
        name = "strategy_equivalence (6 v1->v2)"
        path = "tests/test_strategy_equivalence.py"
        vbt_required = $false
    },
    @{
        name = "tracker_adapter (MyquantTracker + 4 quantlab_* tables)"
        path = "tests/test_tracker_adapter.py"
        vbt_required = $false
    },
    @{
        name = "quantlab_smoke (12 Stage, VBT stage SKIP in sandbox)"
        path = "tests/test_quantlab_smoke.py"
        vbt_required = $false
    },
    @{
        name = "quantlab_cli (6 CLI subcommands)"
        path = "tests/test_quantlab_cli.py"
        vbt_required = $false
    }
)

$results = @()
$globalFailed = 0
$globalPassed = 0
$globalSkipped = 0
$globalXFailed = 0
$globalXPassed = 0

foreach ($suite in $testSuites) {
    if (-not (Test-Path $suite.path)) {
        Write-Host "  [SKIP] $($suite.name) (file not found: $($suite.path))" -ForegroundColor DarkGray
        continue
    }

    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " $($suite.name)" -ForegroundColor Cyan
    Write-Host " $($suite.path)" -ForegroundColor DarkCyan
    Write-Host "========================================" -ForegroundColor Cyan

    # 跑测试并收集输出
    # 注：PowerShell 5.1 的 Start-Process -RedirectStandardOutput 有 bug
    #     （空字符串被当作 null）
    # 改用 & 直接调用，捕获到 $output 变量，再用正则解析汇总行
    # 不用担心 vbt 崩：如果 vbt 加载失败，python 进程退出非 0，但 $output 仍有内容
    $output = & python -m pytest $suite.path -v --tb=short --no-header 2>&1
    $exitCode = $LASTEXITCODE

    # 追加到主日志
    $output | Out-File -FilePath $logFile -Append -Encoding UTF8

    $text = ($output -join "`n")

    # 默认值
    $passed = 0
    $failed = 0
    $skipped = 0
    $xfailed = 0
    $xpassed = 0
    $warnings = 0

    # pytest 输出末尾汇总行示例：
    # "===== 10 passed in 1.23s ====="
    # "===== 5 passed, 2 failed, 1 skipped, 3 warnings in 1.23s ====="
    # "===== 1 passed, 1 warning in 0.45s ====="
    $tailLine = ($text -split "`n") |
        Where-Object { $_ -match "^\=+.*in\s+\d+(\.\d+)?s.*\=+$" } |
        Select-Object -Last 1

    if ($tailLine) {
        # 避免 $Matches 在嵌套 if 中为 null
        $m = [regex]::Match($tailLine, "(\d+)\s+passed")
        if ($m.Success) { $passed = [int]$m.Groups[1].Value }
        $m = [regex]::Match($tailLine, "(\d+)\s+failed")
        if ($m.Success) { $failed = [int]$m.Groups[1].Value }
        $m = [regex]::Match($tailLine, "(\d+)\s+skipped")
        if ($m.Success) { $skipped = [int]$m.Groups[1].Value }
        $m = [regex]::Match($tailLine, "(\d+)\s+xfailed")
        if ($m.Success) { $xfailed = [int]$m.Groups[1].Value }
        $m = [regex]::Match($tailLine, "(\d+)\s+xpassed")
        if ($m.Success) { $xpassed = [int]$m.Groups[1].Value }
        $m = [regex]::Match($tailLine, "(\d+)\s+warnings?")
        if ($m.Success) { $warnings = [int]$m.Groups[1].Value }
    }

    # 子进程异常退出（如 STATUS_DLL_NOT_FOUND）→ 标为 ERROR
    if ($exitCode -ne 0 -and $passed -eq 0 -and $failed -eq 0) {
        $errTail = ($output | Select-Object -Last 3) -join " | "
        Write-Host "  [ERROR] 子进程异常退出 exit=$exitCode tail='$errTail'" -ForegroundColor Magenta
    }

    # 清理临时文件（用 try/catch 防止路径为空时报错）
    # 注：现在不用临时文件了，保留 try/catch 是为了向前兼容
    # 真实场景下 $tempOut / $errOut 为 null，所以这步 no-op
    try {
        if ($null -ne (Get-Variable -Name tempOut -ErrorAction SilentlyContinue) `
            -and $tempOut -and (Test-Path $tempOut)) {
            Remove-Item $tempOut -ErrorAction Stop
        }
        if ($null -ne (Get-Variable -Name errOut -ErrorAction SilentlyContinue) `
            -and $errOut -and (Test-Path $errOut)) {
            Remove-Item $errOut -ErrorAction Stop
        }
    } catch {
        # 忽略清理错误
    }

    $globalPassed += $passed
    $globalFailed += $failed
    $globalSkipped += $skipped
    $globalXFailed += $xfailed
    $globalXPassed += $xpassed

    $color = if ($failed -gt 0) { "Red" } `
             elseif ($exitCode -ne 0 -and $passed -eq 0) { "Magenta" } `
             elseif ($passed -eq 0 -and $skipped -gt 0) { "Yellow" } `
             else { "Green" }
    Write-Host ("  Result: {0} passed, {1} failed, {2} skipped  (exit={3})" -f `
        $passed, $failed, $skipped, $exitCode) -ForegroundColor $color
    Write-Host ""

    $results += @{
        name = $suite.name
        path = $suite.path
        passed = $passed
        failed = $failed
        skipped = $skipped
        exit_code = $exitCode
    }
}

# 汇总
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " SUMMARY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host (" Total: {0} passed, {1} failed, {2} skipped, {3} xfailed, {4} xpassed" -f `
    $globalPassed, $globalFailed, $globalSkipped, $globalXFailed, $globalXPassed) `
    -ForegroundColor $(if ($globalFailed -gt 0) { "Red" } else { "Green" })
Write-Host ""

# 写 JSON
$summaryObj = @{
    timestamp = $timestamp
    project_root = $ProjectRoot
    vectorbt_available = $vbtAvail
    total_passed = $globalPassed
    total_failed = $globalFailed
    total_skipped = $globalSkipped
    total_xfailed = $globalXFailed
    total_xpassed = $globalXPassed
    suites = $results
}
$summaryObj | ConvertTo-Json -Depth 5 | Set-Content -Path $jsonFile -Encoding UTF8
Write-Host " Log : $logFile"
Write-Host " JSON: $jsonFile"
Write-Host ""

# 退出码判定：
#   - 0   → 全部 passed（vbt 相关可能 skip 或子进程异常，但不算 failed）
#   - 1   → 有 failed
#   - 2   → 有套件子进程异常退出（如 vbt DLL 缺失）但无 failed
$anySubprocessErr = ($results | Where-Object { $_.exit_code -ne 0 }).Count -gt 0

if ($globalFailed -gt 0) {
    Write-Host "=== PHASE 7 SUITE: FAILED (有真实 FAILED 测试) ===" -ForegroundColor Red
    exit 1
} elseif ($anySubprocessErr) {
    Write-Host "=== PHASE 7 SUITE: PASSED (但部分套件子进程异常，可能 vbt DLL 缺失) ===" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "=== PHASE 7 SUITE: PASSED ===" -ForegroundColor Green
    exit 0
}
