import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:font_awesome_flutter/font_awesome_flutter.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:dio/dio.dart';
import 'package:http/http.dart' as http;
import 'package:html/parser.dart' as parser;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:youtube_explode_dart/youtube_explode_dart.dart' as yt_explode;
import 'package:gal/gal.dart';
import 'package:intl/intl.dart';
// Updated Imports for ffmpeg_kit_flutter_new
import 'package:ffmpeg_kit_flutter_new/ffmpeg_kit.dart';
import 'package:ffmpeg_kit_flutter_new/return_code.dart';

void main() {
  runApp(const MediaFlowApp());
}

// --- Data Models ---

class DownloadRecord {
  final String id;
  final String title;
  final String platform;
  final String filePath;
  final DateTime date;
  final String type;

  DownloadRecord({
    required this.id,
    required this.title,
    required this.platform,
    required this.filePath,
    required this.date,
    required this.type,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'platform': platform,
        'filePath': filePath,
        'date': date.toIso8601String(),
        'type': type,
      };

  factory DownloadRecord.fromJson(Map<String, dynamic> json) => DownloadRecord(
        id: json['id'],
        title: json['title'],
        platform: json['platform'],
        filePath: json['filePath'],
        date: DateTime.parse(json['date']),
        type: json['type'],
      );
}

class MediaMetadata {
  final String title;
  final String author;
  final String thumbnailUrl;
  final bool isYouTube;

  MediaMetadata({
    required this.title,
    required this.author,
    required this.thumbnailUrl,
    required this.isYouTube,
  });
}

class StreamOption {
  final String label;
  final yt_explode.StreamInfo streamInfo;
  final bool needsMerge;

  StreamOption({required this.label, required this.streamInfo, required this.needsMerge});
}

// --- Services ---

class HistoryService {
  static Future<String> get _localPath async {
    final directory = await getApplicationDocumentsDirectory();
    return directory.path;
  }

  static Future<File> get _localFile async {
    final path = await _localPath;
    return File('$path/history.json');
  }

  static Future<List<DownloadRecord>> getHistory() async {
    try {
      final file = await _localFile;
      if (!await file.exists()) return [];
      final contents = await file.readAsString();
      final List<dynamic> jsonList = jsonDecode(contents);
      return jsonList.map((e) => DownloadRecord.fromJson(e)).toList();
    } catch (e) {
      return [];
    }
  }

  static Future<void> addRecord(DownloadRecord record) async {
    final history = await getHistory();
    history.insert(0, record);
    final file = await _localFile;
    await file.writeAsString(jsonEncode(history.map((e) => e.toJson()).toList()));
  }
}

// --- Main App ---

class MediaFlowApp extends StatelessWidget {
  const MediaFlowApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MediaFlow',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.dark(
          primary: const Color(0xFF6C5CE7),
          secondary: const Color(0xFFA29BFE),
          surface: const Color(0xFF2D3436),
          background: const Color(0xFF1E272E),
        ),
        scaffoldBackgroundColor: const Color(0xFF1E272E),
        textTheme: GoogleFonts.poppinsTextTheme(ThemeData.dark().textTheme),
      ),
      home: const MainScreen(),
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _selectedIndex = 0;

  final List<Widget> _pages = [
    const HomePage(),
    const DownloadsPage(),
    const SettingsPage(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _selectedIndex,
        children: _pages,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (int index) {
          setState(() {
            _selectedIndex = index;
          });
        },
        backgroundColor: const Color(0xFF2D3436),
        indicatorColor: const Color(0xFF6C5CE7),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home, color: Colors.white),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history, color: Colors.white),
            label: 'History',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings, color: Colors.white),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}

// --- HOME PAGE ---

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String selectedPlatform = 'YouTube';
  final Map<String, TextEditingController> _controllers = {};
  
  bool isFetching = false;
  bool isDownloading = false;
  double downloadProgress = 0.0;
  String statusMessage = "";

  MediaMetadata? fetchedMedia;
  yt_explode.Video? _youtubeVideoData;
  List<StreamOption>? availableQualities;
  StreamOption? selectedQuality;
  bool isPlaylist = false;
  List<yt_explode.Video>? playlistVideos;

  final Map<String, dynamic> platforms = {
    'YouTube': {'icon': FontAwesomeIcons.youtube, 'color': Colors.redAccent},
    'Instagram': {'icon': FontAwesomeIcons.instagram, 'color': Colors.purpleAccent},
    'Freepik': {'icon': FontAwesomeIcons.image, 'color': Colors.blueAccent},
    'Shutterstock': {'icon': FontAwesomeIcons.camera, 'color': Colors.red},
    'TikTok': {'icon': FontAwesomeIcons.tiktok, 'color': Colors.tealAccent},
  };

  @override
  void initState() {
    super.initState();
    for (var key in platforms.keys) {
      _controllers[key] = TextEditingController();
    }
  }

  @override
  void dispose() {
    for (var controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  TextEditingController get _currentController => _controllers[selectedPlatform]!;

  Future<void> _pasteFromClipboard() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (data?.text != null) {
      setState(() {
        _currentController.text = data!.text!;
      });
    }
  }

  Future<void> _checkLink() async {
    final url = _currentController.text.trim();
    if (url.isEmpty) {
      _showSnackBar('Please paste a valid URL', Colors.orange);
      return;
    }

    setState(() {
      isFetching = true;
      statusMessage = "Analyzing Link...";
      fetchedMedia = null;
      _youtubeVideoData = null;
      playlistVideos = null;
      isPlaylist = false;
      availableQualities = null;
      selectedQuality = null;
    });

    try {
      if (selectedPlatform == 'YouTube') {
        await _analyzeYouTube(url);
      } else {
        // Attempt initial scrape just to get title/thumb
        String? thumbUrl;
        String title = 'External Media';
        
        try {
           if (url.contains('freepik')) title = 'Freepik Image';
           if (url.contains('shutterstock')) title = 'Shutterstock Media';
           if (url.contains('instagram')) title = 'Instagram Post';

           fetchedMedia = MediaMetadata(
             title: title,
             author: selectedPlatform,
             thumbnailUrl: '', // Will try to populate later or use generic icon
             isYouTube: false,
           );
        } catch (e) { /* Ignore */ }

        setState(() {});
      }
    } catch (e) {
      _showSnackBar('Error: $e', Colors.red);
    } finally {
      setState(() => isFetching = false);
    }
  }

  Future<void> _analyzeYouTube(String url) async {
    var yt = yt_explode.YoutubeExplode();
    try {
      if (url.contains('list=')) {
        final playlist = await yt.playlists.get(url);
        final videos = await yt.playlists.getVideos(playlist.id).take(50).toList();
        setState(() {
          isPlaylist = true;
          playlistVideos = videos;
          statusMessage = "Playlist Detected";
        });
      } else {
        var video = await yt.videos.get(url);
        var manifest = await yt.videos.streamsClient.getManifest(url);
        
        List<StreamOption> options = [];

        // 1. Muxed (Standard 720p/360p)
        var muxed = manifest.muxed.toList();
        muxed.sort((a, b) => b.videoQuality.index.compareTo(a.videoQuality.index));
        for (var s in muxed) {
          options.add(StreamOption(
            label: "Standard ${s.videoQuality.name} (${(s.size.totalMegaBytes).toStringAsFixed(1)} MB)",
            streamInfo: s,
            needsMerge: false
          ));
        }

        // 2. Video Only (1080p+)
        var videoOnly = manifest.videoOnly.where((e) => e.videoQuality.index > yt_explode.VideoQuality.high720.index).toList();
        videoOnly.sort((a, b) => b.videoQuality.index.compareTo(a.videoQuality.index));

        for (var s in videoOnly) {
           options.add(StreamOption(
            label: "High Quality ${s.videoQuality.name} (${(s.size.totalMegaBytes).toStringAsFixed(1)} MB)",
            streamInfo: s,
            needsMerge: true
          ));
        }

        setState(() {
          _youtubeVideoData = video;
          fetchedMedia = MediaMetadata(
            title: video.title,
            author: video.author,
            thumbnailUrl: video.thumbnails.mediumResUrl,
            isYouTube: true,
          );
          availableQualities = options;
          selectedQuality = options.isNotEmpty ? options.first : null;
        });
      }
    } catch (e) {
      throw Exception("Could not fetch YouTube info.");
    } finally {
      yt.close();
    }
  }

  Future<void> _startDownload() async {
    if (fetchedMedia == null && !isPlaylist) return;
    
    await Permission.storage.request();
    await Permission.photos.request();

    setState(() {
      isDownloading = true;
      downloadProgress = 0.0;
      statusMessage = "Initializing...";
    });

    try {
      String savedPath = "";
      String title = "";

      if (selectedPlatform == 'YouTube' && fetchedMedia!.isYouTube) {
        if (selectedQuality == null) throw Exception("No quality selected");
        title = fetchedMedia!.title;
        
        if (selectedQuality!.needsMerge) {
           savedPath = await _downloadAndMergeYouTube(_youtubeVideoData!, selectedQuality!.streamInfo);
        } else {
           savedPath = await _downloadYouTubeStream(_youtubeVideoData!, selectedQuality!.streamInfo);
        }

      } else {
        title = fetchedMedia!.title;
        savedPath = await _downloadGenericOrScraped(_currentController.text.trim());
      }

      final record = DownloadRecord(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        title: title,
        platform: selectedPlatform,
        filePath: savedPath,
        date: DateTime.now(),
        type: savedPath.endsWith('.mp4') ? 'video' : 'image',
      );
      await HistoryService.addRecord(record);

      _showSnackBar('Download Complete! Saved to Gallery.', Colors.green);
      
      setState(() {
        isDownloading = false;
        downloadProgress = 1.0;
      });

    } catch (e) {
      setState(() {
        isDownloading = false;
        statusMessage = "Failed: $e";
      });
      _showSnackBar('Failed: $e', Colors.red);
    }
  }

  Future<String> _downloadYouTubeStream(yt_explode.Video video, yt_explode.StreamInfo streamInfo) async {
    var yt = yt_explode.YoutubeExplode();
    try {
      var dir = await getTemporaryDirectory();
      String safeTitle = video.title.replaceAll(RegExp(r'[^\w\s]+'), '');
      String filePath = '${dir.path}/${safeTitle}_${DateTime.now().millisecondsSinceEpoch}.mp4';
      
      var file = File(filePath);
      var stream = yt.videos.streamsClient.get(streamInfo);
      var fileStream = file.openWrite();
      
      var total = streamInfo.size.totalBytes;
      var count = 0;

      await stream.listen((data) {
        count += data.length;
        fileStream.add(data);
        setState(() {
          downloadProgress = count / total;
          statusMessage = "Downloading Video...";
        });
      }).asFuture();

      await fileStream.flush();
      await fileStream.close();
      await Gal.putVideo(filePath);
      return filePath;
    } finally {
      yt.close();
    }
  }

  Future<String> _downloadAndMergeYouTube(yt_explode.Video video, yt_explode.StreamInfo videoStreamInfo) async {
    var yt = yt_explode.YoutubeExplode();
    try {
      var dir = await getTemporaryDirectory();
      String safeTitle = video.title.replaceAll(RegExp(r'[^\w\s]+'), '');
      String timestamp = DateTime.now().millisecondsSinceEpoch.toString();
      
      String videoPath = '${dir.path}/temp_video_$timestamp.mp4';
      String audioPath = '${dir.path}/temp_audio_$timestamp.mp4';
      String outputPath = '${dir.path}/${safeTitle}_hq.mp4';

      // 1. Get Audio Stream
      var manifest = await yt.videos.streamsClient.getManifest(video.id);
      var audioStreamInfo = manifest.audioOnly.withHighestBitrate();

      // 2. Download Video
      setState(() => statusMessage = "Downloading Video Track...");
      await _simpleDownload(yt, videoStreamInfo, File(videoPath));

      // 3. Download Audio
      setState(() => statusMessage = "Downloading Audio Track...");
      await _simpleDownload(yt, audioStreamInfo, File(audioPath));

      // 4. Merge with FFmpeg
      setState(() => statusMessage = "Merging Audio & Video...");
      
      String command = "-i \"$videoPath\" -i \"$audioPath\" -c:v copy -c:a aac \"$outputPath\"";
      
      await FFmpegKit.execute(command).then((session) async {
        final returnCode = await session.getReturnCode();
        if (!ReturnCode.isSuccess(returnCode)) {
          throw Exception("FFmpeg merge failed");
        }
      });

      // 5. Clean up temps and Save
      await File(videoPath).delete();
      await File(audioPath).delete();

      await Gal.putVideo(outputPath);
      return outputPath;
    } finally {
      yt.close();
    }
  }

  Future<void> _simpleDownload(yt_explode.YoutubeExplode yt, yt_explode.StreamInfo info, File file) async {
    var stream = yt.videos.streamsClient.get(info);
    var fileStream = file.openWrite();
    await stream.pipe(fileStream);
    await fileStream.flush();
    await fileStream.close();
  }

  // --- ENHANCED SCRAPER ---
  
  Future<String> _downloadGenericOrScraped(String url) async {
    setState(() => statusMessage = "Scanning page for media...");
    
    String? downloadUrl;
    
    // 1. Try scraping direct URL
    downloadUrl = await _scrapeMediaUrl(url);
    
    // 2. Fallback: Check if URL is direct link
    if (downloadUrl == null) {
      if (url.contains('.mp4') || url.contains('.jpg') || url.contains('.png')) {
        downloadUrl = url;
      } else {
        throw Exception("Could not find a public video/image. Account might be private.");
      }
    }

    setState(() => statusMessage = "Downloading file...");
    Dio dio = Dio();
    var dir = await getTemporaryDirectory();
    
    String extension = 'jpg';
    if (downloadUrl.contains('.mp4')) extension = 'mp4';
    if (downloadUrl.contains('.png')) extension = 'png';
    
    String filePath = '${dir.path}/media_${DateTime.now().millisecondsSinceEpoch}.$extension';
    
    await dio.download(downloadUrl, filePath, onReceiveProgress: (rec, total) {
      if (total != -1) {
        setState(() {
          downloadProgress = rec / total;
        });
      }
    });

    if (extension == 'mp4') {
      await Gal.putVideo(filePath);
    } else {
      await Gal.putImage(filePath);
    }
    
    return filePath;
  }

  Future<String?> _scrapeMediaUrl(String url) async {
    try {
      // Basic headers to look like a browser
      var response = await http.get(Uri.parse(url), headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
      });

      var body = response.body;
      var document = parser.parse(body);

      // 1. Meta Tags (Freepik/Shutterstock Preview)
      var ogVideo = document.querySelector('meta[property="og:video"]')?.attributes['content'];
      if (ogVideo != null) return ogVideo;
      
      var ogImage = document.querySelector('meta[property="og:image"]')?.attributes['content'];
      if (ogImage != null && !url.contains("instagram.com")) return ogImage;

      // 2. Regex for JSON data (Instagram/Generic)
      // Matches "video_url":"https://..." or "display_url":"https://..."
      
      // Video URL
      final videoRegex = RegExp(r'"video_url"\s*:\s*"([^"]+)"');
      final videoMatch = videoRegex.firstMatch(body);
      if (videoMatch != null) {
        return _cleanUrl(videoMatch.group(1)!);
      }

      // Display URL (Images)
      final imageRegex = RegExp(r'"display_url"\s*:\s*"([^"]+)"');
      final imageMatch = imageRegex.firstMatch(body);
      if (imageMatch != null) {
        return _cleanUrl(imageMatch.group(1)!);
      }
      
      // 3. Generic MP4 finding
      final mp4Regex = RegExp(r'(https?://[^"]+\.mp4)');
      final mp4Match = mp4Regex.firstMatch(body);
      if (mp4Match != null) {
         return _cleanUrl(mp4Match.group(0)!);
      }

      return null;
    } catch (e) {
      print("Scrape error: $e");
      return null;
    }
  }

  String _cleanUrl(String url) {
    // Fixes unicode escapes (\u0026 -> &) and escaped slashes (\/ -> /)
    return url.replaceAll(r'\/', '/').replaceAll(r'\u0026', '&');
  }

  void _showSnackBar(String message, Color color) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: color),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('MediaFlow', style: GoogleFonts.poppins(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.white)),
                      Text('Download media seamlessly', style: TextStyle(color: Colors.grey[400], fontSize: 14)),
                    ],
                  ),
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(color: const Color(0xFF6C5CE7).withOpacity(0.2), borderRadius: BorderRadius.circular(12)),
                    child: const Icon(Icons.cloud_download, color: Color(0xFF6C5CE7)),
                  ),
                ],
              ),
              const SizedBox(height: 30),

              // Platform Selector
              SizedBox(
                height: 100,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: platforms.entries.map((entry) {
                    final isSelected = selectedPlatform == entry.key;
                    return GestureDetector(
                      onTap: () => setState(() {
                        selectedPlatform = entry.key;
                        fetchedMedia = null;
                        _youtubeVideoData = null;
                        isPlaylist = false;
                      }),
                      child: Container(
                        width: 80,
                        margin: const EdgeInsets.only(right: 16),
                        decoration: BoxDecoration(
                          color: isSelected ? entry.value['color'].withOpacity(0.2) : const Color(0xFF2D3436),
                          border: isSelected ? Border.all(color: entry.value['color'], width: 2) : null,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(entry.value['icon'], color: isSelected ? entry.value['color'] : Colors.grey, size: 30),
                            const SizedBox(height: 8),
                            Text(entry.key, style: TextStyle(color: isSelected ? Colors.white : Colors.grey, fontSize: 12)),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ),

              const SizedBox(height: 30),

              // Input Area
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(color: const Color(0xFF2D3436), borderRadius: BorderRadius.circular(20)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Paste Link ($selectedPlatform)', style: TextStyle(color: Colors.grey[400], fontSize: 14)),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _currentController,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'https://www.$selectedPlatform.com/...',
                        hintStyle: TextStyle(color: Colors.grey[600]),
                        filled: true,
                        fillColor: const Color(0xFF1E272E),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                        suffixIcon: IconButton(
                          icon: const Icon(Icons.paste, color: Color(0xFF6C5CE7)), 
                          onPressed: _pasteFromClipboard,
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    
                    // CHECK BUTTON
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: ElevatedButton(
                        onPressed: isFetching ? null : _checkLink,
                        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF6C5CE7), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
                        child: isFetching 
                          ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white))
                          : Text(fetchedMedia == null ? 'Check Link' : 'Update Link', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ],
                ),
              ),

              // --- PLAYLIST LIST VIEW ---
              if (isPlaylist && playlistVideos != null) ...[
                 const SizedBox(height: 20),
                 Text("Playlist Detected (${playlistVideos!.length} items)", style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                 const SizedBox(height: 10),
                 ...playlistVideos!.map((video) => Container(
                   margin: const EdgeInsets.only(bottom: 10),
                   decoration: BoxDecoration(color: const Color(0xFF2D3436), borderRadius: BorderRadius.circular(12)),
                   child: ListTile(
                     leading: ClipRRect(
                       borderRadius: BorderRadius.circular(8),
                       child: Image.network(video.thumbnails.mediumResUrl, width: 80, fit: BoxFit.cover,
                         errorBuilder: (c,o,s) => Container(color: Colors.grey, width: 80)),
                     ),
                     title: Text(video.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white)),
                     subtitle: Text(video.author, style: const TextStyle(color: Colors.grey)),
                     trailing: IconButton(
                       icon: const Icon(Icons.download, color: Color(0xFF6C5CE7)),
                       onPressed: () {
                         _currentController.text = "https://youtube.com/watch?v=${video.id}";
                         _checkLink();
                       },
                     ),
                   ),
                 )),
              ],

              // --- PREVIEW BOX & DOWNLOADER ---
              if (fetchedMedia != null && !isPlaylist) ...[
                const SizedBox(height: 20),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: const Color(0xFF2D3436),
                    border: Border.all(color: const Color(0xFF6C5CE7).withOpacity(0.5)),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Column(
                    children: [
                      // Thumb & Title
                      Row(
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: fetchedMedia!.thumbnailUrl.isNotEmpty
                              ? Image.network(
                                  fetchedMedia!.thumbnailUrl, 
                                  width: 100, 
                                  height: 60, 
                                  fit: BoxFit.cover,
                                  errorBuilder: (c,o,s) => Container(width: 100, height: 60, color: Colors.grey),
                                )
                              : Container(width: 100, height: 60, color: Colors.grey, child: const Icon(Icons.link)),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  fetchedMedia!.title,
                                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                Text(fetchedMedia!.author, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      
                      // Quality Selector (YouTube Only)
                      if (fetchedMedia!.isYouTube && availableQualities != null)
                        DropdownButtonFormField<StreamOption>(
                          value: selectedQuality,
                          dropdownColor: const Color(0xFF2D3436),
                          decoration: InputDecoration(
                            labelText: 'Select Quality',
                            labelStyle: const TextStyle(color: Colors.grey),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                          ),
                          items: availableQualities!.map((s) {
                            return DropdownMenuItem(
                              value: s,
                              child: Text(s.label),
                            );
                          }).toList(),
                          onChanged: (val) => setState(() => selectedQuality = val),
                        ),

                      const SizedBox(height: 16),
                      
                      // Download Button
                      SizedBox(
                        width: double.infinity,
                        height: 50,
                        child: ElevatedButton(
                          onPressed: isDownloading ? null : _startDownload,
                          style: ElevatedButton.styleFrom(backgroundColor: Colors.green, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
                          child: isDownloading 
                           ? const CircularProgressIndicator(color: Colors.white)
                           : const Row(
                               mainAxisAlignment: MainAxisAlignment.center,
                               children: [
                                 Icon(Icons.download),
                                 SizedBox(width: 8),
                                 Text('Download Media', style: TextStyle(fontWeight: FontWeight.bold)),
                                ],
                             ),
                        ),
                      ),
                      
                      if (isDownloading) ...[
                        const SizedBox(height: 10),
                        LinearProgressIndicator(value: downloadProgress, color: const Color(0xFF6C5CE7)),
                        Text(statusMessage, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                      ]
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// --- HISTORY PAGE ---

class DownloadsPage extends StatelessWidget {
  const DownloadsPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Downloads History'),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh), 
            onPressed: () {
              (context as Element).markNeedsBuild();
            },
          )
        ],
      ),
      body: FutureBuilder<List<DownloadRecord>>(
        future: HistoryService.getHistory(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (!snapshot.hasData || snapshot.data!.isEmpty) {
            return Center(child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.history, size: 80, color: Colors.grey[700]),
                const SizedBox(height: 10),
                Text('No downloads yet', style: TextStyle(color: Colors.grey[500])),
              ],
            ));
          }

          final records = snapshot.data!;
          return ListView.builder(
            itemCount: records.length,
            itemBuilder: (context, index) {
              final item = records[index];
              return ListTile(
                leading: CircleAvatar(
                  backgroundColor: item.type == 'video' ? Colors.red.withOpacity(0.2) : Colors.blue.withOpacity(0.2),
                  child: Icon(
                    item.type == 'video' ? Icons.videocam : Icons.image,
                    color: item.type == 'video' ? Colors.red : Colors.blue,
                  ),
                ),
                title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text("${item.platform} • ${DateFormat('MMM d, h:mm a').format(item.date)}"),
                trailing: const Icon(Icons.check_circle, color: Colors.green, size: 16),
                onTap: () {
                },
              );
            },
          );
        },
      ),
    );
  }
}

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings'), backgroundColor: Colors.transparent, elevation: 0),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.folder, color: Color(0xFF6C5CE7)),
            title: const Text('Save Location'),
            subtitle: const Text('Gallery / Photos App'),
          ),
          ListTile(
            leading: const Icon(Icons.info, color: Color(0xFF6C5CE7)),
            title: const Text('About MediaFlow'),
            subtitle: const Text('Version 1.3.1'),
          ),
        ],
      ),
    );
  }
}