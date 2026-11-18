import 'package:flutter_test/flutter_test.dart';
import 'package:gipsy/voice.dart';

void main() {
  group('wake phrase', () {
    test('matches the ways Whisper spells it', () {
      for (final s in ['Hey Gipsy.', 'hey gypsy', 'Hey, Gipsy!', 'Hi Jipsy', 'Gipsy', 'Okay Gypsy.']) {
        expect(afterWakePhrase(s), '', reason: s);
      }
    });
    test('returns the command after the wake phrase', () {
      expect(afterWakePhrase("Hey Gipsy, what's the time?"), "what's the time?");
      expect(afterWakePhrase('hey gypsy turn on the lamp'), 'turn on the lamp');
    });
    test('ignores normal speech', () {
      expect(afterWakePhrase('I was talking about hay fever'), isNull);
      expect(afterWakePhrase('the gipsy king'), isNull);
    });
  });

  test('sentence splitter keeps order and merges short bits', () {
    final sp = SentenceSplitter();
    final out = <String>[];
    for (final tok in ['Hello John. ', 'Ok. ', 'Systems are ', 'all nominal today! ', 'Bye']) {
      out.addAll(sp.add(tok));
    }
    out.add(sp.flush());
    expect(out, ['Hello John. Ok.', 'Systems are all nominal today!', 'Bye']);
  });

  test('kaiju alert phrase', () {
    expect(kaijuPhrase.hasMatch(afterWakePhrase("Hey Gipsy, there's a kaiju!")!), isTrue);
    expect(kaijuPhrase.hasMatch('Kaiju alert'), isTrue);
    expect(kaijuPhrase.hasMatch("what's the weather"), isFalse);
  });
}
