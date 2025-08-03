from flask import Flask, request, jsonify
import subprocess
import os 
app = Flask(__name__)

@app.route('/convert', methods=['POST'])
def convert_video():
    data = request.json
    input_path = data.get('input_path')
    output_path = data.get('output_path')

    if not input_path or not output_path:
        return jsonify({'error': 'input_path and output_path required'}), 400

    # Example: run FFmpeg conversion (e.g., to mp4)
    try:
        command = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264', '-preset', 'fast',
            '-c:a', 'aac', output_path
        ]
        subprocess.run(command, check=True)
        return jsonify({'message': 'Conversion successful', 'output': output_path})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)