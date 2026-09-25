/// IST wall-clock values for display; never serialize the shifted value.
class IstTime {
  static const offset = Duration(hours: 5, minutes: 30);
  static DateTime display(DateTime instant) => instant.toUtc().add(offset);
  static String clock(DateTime instant) {
    final time = display(instant);
    return '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')} IST';
  }
}
