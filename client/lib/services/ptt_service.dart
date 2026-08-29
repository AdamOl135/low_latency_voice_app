import 'dart:async';
import 'package:flutter/services.dart';

enum InputActivationMode { voiceActivity, pushToTalk }

/// Push-to-Talk (PTT) hotkey service managing key capture and transmission state.
class PttService {
  InputActivationMode _mode = InputActivationMode.voiceActivity;
  LogicalKeyboardKey _hotkey = LogicalKeyboardKey.capsLock;
  bool _isPressed = false;

  final StreamController<bool> _pttStateController =
      StreamController<bool>.broadcast();
  Stream<bool> get pttStateStream => _pttStateController.stream;

  InputActivationMode get mode => _mode;
  LogicalKeyboardKey get hotkey => _hotkey;
  bool get isPressed => _isPressed;
  bool get isPttMode => _mode == InputActivationMode.pushToTalk;

  void setMode(InputActivationMode mode) {
    _mode = mode;
    if (_mode == InputActivationMode.voiceActivity) {
      _isPressed = false;
      _pttStateController.add(false);
    }
  }

  void setHotkey(LogicalKeyboardKey key) {
    _hotkey = key;
  }

  /// Handles raw key events from the Flutter focus tree.
  bool handleKeyEvent(KeyEvent event) {
    if (_mode != InputActivationMode.pushToTalk) return false;

    if (event.logicalKey == _hotkey) {
      if (event is KeyDownEvent && !_isPressed) {
        _isPressed = true;
        _pttStateController.add(true);
        return true;
      } else if (event is KeyUpEvent && _isPressed) {
        _isPressed = false;
        _pttStateController.add(false);
        return true;
      }
    }
    return false;
  }

  void setPressedDirectly(bool pressed) {
    if (_isPressed != pressed) {
      _isPressed = pressed;
      _pttStateController.add(pressed);
    }
  }

  void dispose() {
    _pttStateController.close();
  }
}
