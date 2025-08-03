import 'package:flutter/material.dart';
import 'download_manager.dart';

void main() {
  runApp(MediaFlowApp());
}

class MediaFlowApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MediaFlow',
      theme: ThemeData.dark(),
      home: DownloadPage(),
    );
  }
}

class DownloadPage extends StatefulWidget {
  @override
  _DownloadPageState createState() => _DownloadPageState();
}

class _DownloadPageState extends State<DownloadPage> {
  final TextEditingController _urlController = TextEditingController();
  String _status = '';

  void _startDownload() async {
    final url = _urlController.text.trim();
    if (url.isEmpty) {
      setState(() {
        _status = 'Please enter a URL';
      });
      return;
    }

    setState(() {
      _status = 'Starting download...';
    });

    try {
      final result = await DownloadManager.downloadMedia(url);
      setState(() {
        _status = 'Download completed: $result';
      });
    } catch (e) {
      setState(() {
        _status = 'Error: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('MediaFlow Downloader'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _urlController,
              decoration: InputDecoration(
                labelText: 'Enter media URL (YouTube, Instagram, etc.)',
                border: OutlineInputBorder(),
              ),
            ),
            SizedBox(height: 12),
            ElevatedButton(
              onPressed: _startDownload,
              child: Text('Download'),
            ),
            SizedBox(height: 12),
            Text(_status),
          ],
        ),
      ),
    );
  }
}