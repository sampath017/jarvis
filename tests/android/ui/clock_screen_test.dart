import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import '../../../mobile/lib/services/clock_service.dart';
import '../../../mobile/lib/services/power_state.dart';
import '../../../mobile/lib/ui/screens/clock_screen.dart';
import '../../../mobile/lib/ui/theme.dart';

class FakeClock extends ClockService {
  final actions=<String>[];
  @override
  Future<Map<String,dynamic>> execute(String action,[Map<String,dynamic> arguments=const {}]) async {
    actions.add(action);
    return {
      'alarms':<Map<String,dynamic>>[], 'timers':<Map<String,dynamic>>[],
      'worlds':[{'id':'Asia/Kolkata','city':'Kolkata','time':'12:30:00','date':'Mon, 9 Nov','offset':'+05:30','differenceMinutes':0}],
      'localTime':'12:30:00','localDate':'Monday, 9 November',
      'stopwatch':{'displayElapsed':12345,'running':false,'laps':[]},
      'bedtime':{},'settings':{},'permissions':{'exact':true,'notifications':true,'fullScreen':true},
    };
  }
}
void main(){
  test('duration preserves elapsed hours and fractions',(){expect(clockDuration(3723120,hundredths:true),'1:02:03.12');expect(clockDuration(-5),'00:00');});
  testWidgets('all five clock apps work with assistant power off',(tester)async{
    PowerState.setEnabled(false);final clock=FakeClock();
    await tester.pumpWidget(MaterialApp(theme:AppTheme.darkTheme,home:ClockScreen(service:clock)));
    await tester.pump();expect(find.text('Wake up your way'),findsOneWidget);
    await tester.tap(find.text('Clock').last);await tester.pump();expect(find.text('Kolkata'),findsOneWidget);
    await tester.tap(find.text('Timer').last);await tester.pump();await tester.tap(find.text('5 min'));await tester.pump();expect(clock.actions,contains('timer.start'));
    await tester.tap(find.text('Stopwatch').last);await tester.pump();await tester.tap(find.text('Start'));await tester.pump();expect(clock.actions,contains('stopwatch.start'));
    await tester.tap(find.text('Bedtime').last);await tester.pump();expect(find.text('A gentler end to your day'),findsOneWidget);expect(PowerState.enabled.value,false);
    await tester.pumpWidget(const SizedBox());
  });
  test('platform capability does not consult the assistant switch',()async{
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ClockService.channel,(call)async{
      expect(call.method,'execute');expect((call.arguments as Map)['action'],'timer.pause');return '{"status":"ok"}';
    });
    PowerState.setEnabled(false);expect((await ClockService().execute('timer.pause',{'id':'timer_test'}))['status'],'ok');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ClockService.channel,null);
  });
}
