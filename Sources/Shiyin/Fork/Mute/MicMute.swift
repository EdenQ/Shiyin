import AppKit
import Carbon.HIToolbox
import Foundation

/// F3 錄音中靜音麥克風（fork design §F3）：只有麥克風＋電腦聲音的錄音。麥克風那一聲道寫成 0，電腦聲音照常錄。
/// 上游的檔只留接點（`// MA-FORK(F3)`）：Recorder 的狀態物件、收音檢查、RecordingWriter 的 setMuted、快捷鍵、選單、設定
@MainActor
enum ForkMute {
    /// Recorder 的靜音狀態（`Recorder.mute`）：`@Observable` 的 Recorder 不能在 extension 加存起來的屬性
    @MainActor
    @Observable
    final class State {
        /// 麥克風靜音（fork design §F3.2）
        var micMuted = false
        /// 靜音中現場好像有人在說話（F3.4）：錄音畫面、選單列顯示「打開麥克風」
        var muteHint = false
        @ObservationIgnored var muteHintDismissed = false
        @ObservationIgnored var muteHintNotified = false
        /// 靜音後每秒一筆：麥克風、電腦聲音像不像有人在說話，留最近 20 秒
        @ObservationIgnored var muteTalk: [(mic: Bool, system: Bool)] = []
        /// 提示第一次出現：AppModel 決定要不要送通知（同收音提醒）
        @ObservationIgnored var onMuteHint: (() -> Void)?
        #if DEBUG
        @ObservationIgnored var muteCheck: [String: Any] = [:]
        #endif

        /// 上游 Recorder 開始錄音時的接點
        func resetForStart() {
            micMuted = false
            muteHint = false
            muteHintNotified = false
            muteTalk = []
        }

        /// 上游 Recorder 停止、清掉狀態時的接點
        func resetForStop() {
            micMuted = false
            muteHint = false
        }
    }

    // MARK: 全域快捷鍵 ⌃⌥⌘M（fork design §F3.3）

    /// fork 的快捷鍵 ID 用 0x4D41_xxxx（「MA」＋序號，DF17）：上游 GlobalHotKey 用 1、2、3（5.1 的截圖）…往上加，
    /// 同一個 signature 下撞號時後註冊的那組會靜靜失敗。scripts/fork/hotkey-id-check.py 擋重複
    static let hotKeyID: UInt32 = 0x4D41_0001
    static var onMute: (() -> Void)?
    static var hotKeyRegistered = false

    static func fireHotKey() { onMute?() }

    /// 由 F0 的 `ForkStartup.install` 呼叫，在上游 AppModel 接好快捷鍵、Recorder 的回呼之後
    static func install(_ model: AppModel) {
        onMute = { [weak model] in model?.toggleMicMuteFromHotKey() }
        let started = model.recorder.onStarted
        model.recorder.onStarted = { [weak model] in
            started?()
            GlobalHotKey.shared.setMuteEnabled(AppSettings.muteHotKey && model?.recorder.canMuteMic == true)
        }
        // 錄音結束時關掉 ⌃⌥⌘M：原本是上游 recordingFinished 裡的 1 行接點，改在上游的回呼之前做（fork design §F0.7）
        let finished = model.recorder.onFinished
        model.recorder.onFinished = { result in
            GlobalHotKey.shared.setMuteEnabled(false)
            finished?(result)
        }
        model.recorder.mute.onMuteHint = { [weak model] in model?.muteHintAppeared() }
    }

    /// 上游 AppModel.menuBarSymbol 的接點：靜音中忘了打開的提醒同麥克風的提醒；靜音中是劃掉的麥克風（上游的提醒優先）
    static func menuBarSymbol(_ recorder: Recorder) -> String? {
        if recorder.muteHint { return "mic.badge.xmark" }
        if recorder.micMuted && recorder.micHint == nil && !recorder.idlePrompt { return "mic.slash.circle.fill" }
        return nil
    }
}

extension GlobalHotKey {
    static let muteDisplay = "⌃⌥⌘M"

    var isMuteRegistered: Bool { ForkMute.hotKeyRegistered }

    /// 麥克風＋電腦聲音的錄音開始時打開、停止時關掉（fork design §F3.3）
    func setMuteEnabled(_ enabled: Bool) {
        if enabled {
            ForkMute.hotKeyRegistered = register(ForkMute.hotKeyID, key: kVK_ANSI_M) == noErr
        } else {
            unregister(ForkMute.hotKeyID)
            ForkMute.hotKeyRegistered = false
        }
    }

    /// DEBUG 指令 `hotkey mute` 也用這個模擬
    func fireMute() { ForkMute.fireHotKey() }
}

extension AppSettings {
    static let muteHotKeyKey = "muteHotKey"
    /// 錄音中按 ⌃⌥⌘M 靜音或打開麥克風（fork design §F3.3）；同上游的開關設定，沒設過是開
    static var muteHotKey: Bool {
        UserDefaults.standard.object(forKey: muteHotKeyKey) == nil ? true : UserDefaults.standard.bool(forKey: muteHotKeyKey)
    }
}

extension Recorder {
    var micMuted: Bool { mute.micMuted }
    var muteHint: Bool { mute.muteHint }
    #if DEBUG
    var muteCheck: [String: Any] { mute.muteCheck }
    #endif

    /// 錄音中可以靜音麥克風（F3.1、F3.6）
    var canMuteMic: Bool { isRecording && source == "both" }

    /// 錄音畫面、選單列、通知都用同一句
    static var muteHintText: String {
        String(localized: "麥克風靜音中，現場好像有人在說話。要錄進去的話，打開麥克風。")
    }

    /// 靜音、打開麥克風（fork design §F3.2）：麥克風那一聲道寫成 0，電腦聲音照常錄
    func setMicMuted(_ value: Bool) {
        guard canMuteMic, value != mute.micMuted else { return }
        forkMuteChanged(value)   // 寫檔的聲道；靜音時不做收音提醒，打開後重新計時（30 秒的音量紀錄是真的聲音，照留）
        mute.micMuted = value
        mute.muteTalk = []
        mute.muteHintDismissed = false
        if mute.muteHint { mute.muteHint = false }
        log.info("microphone \(value ? "muted" : "unmuted", privacy: .public)")
    }

    func toggleMicMute() { setMicMuted(!micMuted) }

    /// 提示的「知道了」：這次靜音不再提示，下次靜音重新算
    func dismissMuteHint() {
        mute.muteHintDismissed = true
        if mute.muteHint { mute.muteHint = false }
    }

    /// 忘了打開麥克風（fork design §F3.2、F3.4）：最近 20 秒麥克風像說話 ≥ 10 秒、電腦聲音 ≤ 2 秒。
    /// 上游的收音檢查在靜音中改呼叫這個（`// MA-FORK(F3)`）
    func checkMuted(_ writer: RecordingWriter) {
        let m = mute
        m.muteTalk.append((ForkMute.soundsLikeSpeech(writer, channel: 0), ForkMute.soundsLikeSpeech(writer, channel: 1)))
        if m.muteTalk.count > 20 { m.muteTalk.removeFirst(m.muteTalk.count - 20) }
        let mic = m.muteTalk.filter(\.mic).count
        let system = m.muteTalk.filter(\.system).count
        let show = !m.muteHintDismissed && m.muteTalk.count >= 20 && mic >= 10 && system <= 2
        if show != m.muteHint {
            m.muteHint = show
            if show && !m.muteHintNotified {
                m.muteHintNotified = true
                m.onMuteHint?()
            }
        }
        #if DEBUG
        m.muteCheck = ["mic": mic, "system": system, "seconds": m.muteTalk.count]
        #endif
    }
}

extension ForkMute {
    /// 一個聲道最近像不像有人在說話：同上游 Recorder.soundsLikeSpeech 的一個聲道（上游的那份加了同樣的 1 秒判斷，`// MA-FORK(F3)`）
    nonisolated static func soundsLikeSpeech(_ writer: RecordingWriter, channel: Int) -> Bool {
        // 超過 1 秒沒送資料（音源停了、重新連接中）：最近的音量是停之前的，不算
        guard writer.secondsSinceSamples(channel) < 1 else { return false }
        let levels = writer.recentLevels(channel)
        guard levels.count >= 20 else { return false }
        let background = levels.sorted()[Int(Double(levels.count - 1) * 0.1)]
        let threshold = min(max(background + 12, -50), -40)
        let last = levels.suffix(10)
        return Double(last.filter { $0 > threshold }.count) >= Double(last.count) * 0.3
    }
}

extension AppModel {
    /// ⌃⌥⌘M（fork design §F3.3）：人多半在 Teams 裡，用聲音讓人知道按到了
    func toggleMicMuteFromHotKey() {
        guard recorder.canMuteMic else { return }
        recorder.toggleMicMute()
        NSSound(named: recorder.micMuted ? "Bottle" : "Pop")?.play()
    }

    /// 靜音中現場好像有人在說話（fork design §F3.2、F3.4）：通知的規則同收音提醒
    func muteHintAppeared() {
        guard let id = recorder.meetingId, !mainWindowInFront else { return }
        notifier.levelHint(Recorder.muteHintText, kind: "muted", meetingId: id)
    }
}
