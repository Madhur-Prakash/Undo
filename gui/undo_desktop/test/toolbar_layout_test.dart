// The toolbar row (search field + dropdown + chip + sort button) must lay out without errors.
// An InputDecorator-based dropdown once broke this row in release builds (unbounded width).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:undo_desktop/shared/widgets.dart';

const _options = [
  SortOption('path', 'Path'),
  SortOption('size', 'Size', descendingFirst: true),
];

void main() {
  testWidgets('toolbar row with dropdown and sort control lays out', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    SortState sort = (key: 'path', descending: false);
    int? root;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => Column(children: [
            Row(children: [
              const Expanded(child: TextField(decoration: InputDecoration(hintText: 'Search by path'))),
              const SizedBox(width: 12),
              AppDropdown<int?>(
                value: root,
                items: const [
                  DropdownMenuItem(value: null, child: Text('All roots')),
                  DropdownMenuItem(value: 1, child: Text(r'C:\code_playground\assiugnment')),
                ],
                onChanged: (v) => setState(() => root = v),
              ),
              const SizedBox(width: 12),
              FilterChip(label: const Text('Include deleted'), selected: false, onSelected: (_) {}),
              const SizedBox(width: 12),
              SortControl(options: _options, value: sort, onChanged: (s) => setState(() => sort = s)),
            ]),
            Row(children: [
              Expanded(
                child: SortableHeader(
                  label: 'Size',
                  sortKey: 'size',
                  options: _options,
                  value: sort,
                  onChanged: (s) => setState(() => sort = s),
                ),
              ),
            ]),
          ]),
        ),
      ),
    ));

    expect(tester.takeException(), isNull);
    expect(find.text('All roots'), findsOneWidget);
    expect(find.text('Sort: Path'), findsOneWidget);

    // Clicking a column header sorts by it (natural direction first).
    await tester.tap(find.text('Size'));
    await tester.pump();
    expect(find.text('Sort: Size'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
