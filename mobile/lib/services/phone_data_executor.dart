import 'health_service.dart';
import 'usage_service.dart';

typedef PhoneRecordReader =
    Future<Map<String, dynamic>> Function(Map<String, dynamic> arguments);

/// Runs model-selected reads through the existing private device capability.
class PhoneDataExecutor {
  PhoneDataExecutor({
    PhoneRecordReader? usageReader,
    PhoneRecordReader? healthReader,
  }) : usageReader = usageReader ?? UsageService.readToolRecords,
       healthReader = healthReader ?? HealthService.instance.readToolRecords;
  final PhoneRecordReader usageReader, healthReader;

  Future<Map<String, dynamic>> execute(
    Map<String, dynamic> action, {
    required Future<bool> Function() isActive,
    required bool Function() isForeground,
  }) async {
    if (!isForeground() || !await isActive()) {
      return {
        'status': 'cancelled',
        'reason': 'inactive',
        'message': 'Keep Jarvis open while reading phone records.',
      };
    }
    try {
      final result = switch (action['operation']) {
        'app_usage_read' => await usageReader(action),
        'health_records_read' => await healthReader(action),
        _ => <String, dynamic>{
          'status': 'invalid_arguments',
          'message': 'Unsupported phone data read.',
        },
      };
      if (!isForeground() || !await isActive()) {
        return {
          'status': 'cancelled',
          'reason': 'inactive',
          'message': 'The request ended before the phone read completed.',
        };
      }
      return result;
    } on FormatException catch (error) {
      return {
        'status': 'invalid_arguments',
        'message': error.message.toString(),
      };
    } catch (_) {
      return {
        'status': 'unavailable',
        'reason': 'read_failed',
        'message':
            'The requested phone records could not be read. Do not infer zero or switch data sources.',
      };
    }
  }
}
