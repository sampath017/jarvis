import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'power_state.dart';

class RuntimePowerService extends ChangeNotifier {
  RuntimePowerService({http.Client Function()? controlClientFactory});
  static final instance = RuntimePowerService();
  static const channel = MethodChannel('com.jarvis/power');
  bool initialized = false;
  bool busy = false;
  bool cloudConfirmed = true;
  String? error;
  Future<void> Function()? startServices;
  Future<void> Function()? stopServices;
  bool get enabled => PowerState.enabled.value;

  Future<void> initialize() async {
    Map<String, dynamic> local;
    try {
      local = await channel.invokeMapMethod<String, dynamic>('status') ?? {};
    } catch (_) {
      PowerState.setEnabled(false);
      error = 'Could not read the phone power setting. Please retry.';
      initialized = true;
      notifyListeners();
      return;
    }
    cloudConfirmed = local['cloudConfirmed'] != false;
    var on = local['enabled'] != false;
    // The phone's durable setting works offline. API availability never blocks
    // local notes, recordings, usage, or scheduled reminders on launch.
    // Reading the durable switch must not replay native alarm restoration and
    // activity registration on the UI thread every time the app opens.
    PowerState.setEnabled(on);
    initialized = true;
    notifyListeners();
    if (on) await startServices?.call();
  }

  Future<void> setEnabled(bool value) async {
    if (busy) return;
    busy = true;
    error = null;
    notifyListeners();
    try {
      // Stop the phone first, including when the network is unavailable.
      PowerState.setEnabled(false);
      notifyListeners();
      await channel.invokeMethod('setEnabled', false);
      await channel.invokeMethod('setCloudConfirmed', false);
      cloudConfirmed = false;
      await stopServices?.call();
      if (value) {
        await channel.invokeMethod('setEnabled', true);
        PowerState.setEnabled(true);
        notifyListeners();
        await startServices?.call();
      }
      cloudConfirmed = true;
      await channel.invokeMethod('setCloudConfirmed', cloudConfirmed);
    } catch (_) {
      if (enabled) {
        PowerState.setEnabled(false);
        await channel.invokeMethod('setEnabled', false);
        await stopServices?.call();
        cloudConfirmed = false;
        await channel.invokeMethod('setCloudConfirmed', false);
      }
      error = value
          ? 'Could not update the phone power setting. Please retry.'
          : 'Could not update the phone power setting. Please retry.';
    } finally {
      busy = false;
      notifyListeners();
    }
  }
}
