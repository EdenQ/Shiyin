import SwiftUI

// F3 靜音麥克風的畫面（fork design §F3.3、F3.4）：錄音畫面、選單列、應用程式選單。上游的檔只留接點（`// MA-FORK(F3)`）

/// 靜音、打開麥克風的按鈕（fork design §F3.3）：錄音畫面、選單列共用
struct MicMuteButton: View {
    let recorder: Recorder

    var body: some View {
        Button {
            recorder.toggleMicMute()
        } label: {
            Image(systemName: recorder.micMuted ? "mic.slash.fill" : "mic.fill")
                .foregroundStyle(recorder.micMuted ? Color.red : Color.primary)
                .frame(width: 18)
        }
        .buttonStyle(.borderless)
        .help(recorder.micMuted ? String(localized: "打開麥克風（⇧⌘M）")
                                : String(localized: "靜音麥克風（⇧⌘M）：現場的聲音不錄，電腦聲音照常錄"))
        .accessibilityLabel(recorder.micMuted ? String(localized: "打開麥克風") : String(localized: "靜音麥克風"))
    }
}


/// 錄音畫面上方的提示列：靜音中現場好像有人在說話（fork design §F3.3、F3.4）
struct ForkMuteHintBar: View {
    let recorder: Recorder

    var body: some View {
        if recorder.muteHint {
            HStack(spacing: 12) {
                Label(Recorder.muteHintText, systemImage: "mic.slash")
                Spacer()
                Button("打開麥克風") { recorder.setMicMuted(false) }
                    .buttonStyle(.borderedProminent)
                Button("知道了") { recorder.dismissMuteHint() }
                    .help("這次靜音不再提示這件事")
            }
            .font(.callout)
            .controlSize(.small)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color.signal.opacity(0.12))
        }
    }
}

/// 錄音畫面的麥克風音量：麥克風＋電腦聲音的錄音，麥克風的圖示可以按，靜音麥克風（fork design §F3.3）。
/// 這時上游的「麥克風音量」那一格不顯示（`forkHidden`）
struct ForkMicMuteMeter: View {
    let recorder: Recorder

    var body: some View {
        HStack(spacing: 6) {
            MicMuteButton(recorder: recorder)
            RecorderMeter(recorder: recorder, system: false).opacity(recorder.micMuted ? 0.35 : 1)
            if recorder.micMuted {
                Text("麥克風已靜音").font(.callout).foregroundStyle(.red).fixedSize()
            }
        }
    }
}

extension View {
    /// 上游的元件在 fork 換成自己的版本時不顯示（不佔位置）
    @ViewBuilder func forkHidden(_ hidden: Bool) -> some View {
        if !hidden { self }
    }
}

/// 選單列：靜音麥克風那一列（fork design §F3.3）
struct ForkMuteMenuBarRow: View {
    let recorder: Recorder

    var body: some View {
        if recorder.canMuteMic {
            HStack(spacing: 8) {
                MicMuteButton(recorder: recorder)
                Text(recorder.micMuted ? "麥克風已靜音" : "麥克風")
                    .font(.caption)
                    .foregroundStyle(recorder.micMuted ? Color.red : Color.secondary)
                Spacer()
                Button(recorder.micMuted ? "打開麥克風" : "靜音麥克風") { recorder.toggleMicMute() }
                    .font(.caption)
            }
        }
    }
}

/// 選單列：靜音中現場好像有人在說話（fork design §F3.3）：同錄音畫面
struct ForkMuteMenuBarHint: View {
    let recorder: Recorder

    var body: some View {
        if recorder.muteHint {
            VStack(alignment: .leading, spacing: 6) {
                Label(Recorder.muteHintText, systemImage: "mic.slash")
                    .font(.caption)
                    .foregroundStyle(Color.signal)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("打開麥克風") { recorder.setMicMuted(false) }
                    Button("知道了") { recorder.dismissMuteHint() }
                }
                .font(.caption)
            }
        }
    }
}

/// 應用程式「錄音」選單的「麥克風靜音」⇧⌘M：麥克風＋電腦聲音的錄音才能靜音麥克風（fork design §F3.3）
struct ForkMuteMenuCommand: View {
    let recorder: Recorder

    var body: some View {
        Button(recorder.micMuted ? "打開麥克風" : "麥克風靜音") { recorder.toggleMicMute() }
            .keyboardShortcut("m", modifiers: [.command, .shift])
            .disabled(!recorder.canMuteMic)
    }
}
