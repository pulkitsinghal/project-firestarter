#!/usr/bin/env python3.11
"""
Video Processor - Utilities for processing recorded demo videos
"""

import os
import subprocess
from pathlib import Path
from typing import List, Optional


class VideoProcessor:
    """Process and convert recorded demo videos"""
    
    def __init__(self, recordings_dir: str = "./recordings"):
        """Initialize the video processor"""
        self.recordings_dir = Path(recordings_dir)
    
    def list_recordings(self) -> List[Path]:
        """List all video recordings"""
        videos = list(self.recordings_dir.glob("*.webm"))
        videos.extend(self.recordings_dir.glob("*.mp4"))
        return sorted(videos, key=lambda x: x.stat().st_mtime, reverse=True)
    
    def convert_to_mp4(self, input_file: str, output_file: Optional[str] = None, 
                      quality: str = "high") -> str:
        """
        Convert video to MP4 format
        
        Args:
            input_file: Input video file path
            output_file: Output file path (optional)
            quality: Quality preset ('high', 'medium', 'low')
            
        Returns:
            Path to output file
        """
        input_path = Path(input_file)
        
        if output_file is None:
            output_file = input_path.with_suffix('.mp4')
        
        # Quality settings
        quality_settings = {
            'high': ['-crf', '18', '-preset', 'slow'],
            'medium': ['-crf', '23', '-preset', 'medium'],
            'low': ['-crf', '28', '-preset', 'fast']
        }
        
        cmd = [
            'ffmpeg', '-y',
            '-i', str(input_path),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            *quality_settings.get(quality, quality_settings['high']),
            '-c:a', 'aac',
            '-b:a', '192k',
            str(output_file)
        ]
        
        print(f"Converting {input_path.name} to MP4...")
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Converted to: {output_file}")
        
        return str(output_file)
    
    def trim_video(self, input_file: str, start_time: str, end_time: str, 
                   output_file: Optional[str] = None) -> str:
        """
        Trim video to specific time range
        
        Args:
            input_file: Input video file path
            start_time: Start time (format: HH:MM:SS or seconds)
            end_time: End time (format: HH:MM:SS or seconds)
            output_file: Output file path (optional)
            
        Returns:
            Path to output file
        """
        input_path = Path(input_file)
        
        if output_file is None:
            output_file = input_path.parent / f"{input_path.stem}_trimmed{input_path.suffix}"
        
        cmd = [
            'ffmpeg', '-y',
            '-i', str(input_path),
            '-ss', start_time,
            '-to', end_time,
            '-c', 'copy',
            str(output_file)
        ]
        
        print(f"Trimming {input_path.name}...")
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Trimmed video saved to: {output_file}")
        
        return str(output_file)
    
    def concatenate_videos(self, input_files: List[str], output_file: str) -> str:
        """
        Concatenate multiple videos into one
        
        Args:
            input_files: List of input video file paths
            output_file: Output file path
            
        Returns:
            Path to output file
        """
        # Create temporary file list
        list_file = self.recordings_dir / "concat_list.txt"
        
        with open(list_file, 'w') as f:
            for video in input_files:
                f.write(f"file '{os.path.abspath(video)}'\n")
        
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',
            output_file
        ]
        
        print(f"Concatenating {len(input_files)} videos...")
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Concatenated video saved to: {output_file}")
        
        # Clean up
        list_file.unlink()
        
        return output_file
    
    def add_fade(self, input_file: str, fade_in: float = 0.5, fade_out: float = 0.5,
                output_file: Optional[str] = None) -> str:
        """
        Add fade in/out effects to video
        
        Args:
            input_file: Input video file path
            fade_in: Fade in duration in seconds
            fade_out: Fade out duration in seconds
            output_file: Output file path (optional)
            
        Returns:
            Path to output file
        """
        input_path = Path(input_file)
        
        if output_file is None:
            output_file = input_path.parent / f"{input_path.stem}_fade{input_path.suffix}"
        
        # Get video duration
        duration_cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(input_path)
        ]
        duration = float(subprocess.check_output(duration_cmd).decode().strip())
        
        fade_out_start = duration - fade_out
        
        cmd = [
            'ffmpeg', '-y',
            '-i', str(input_path),
            '-vf', f"fade=t=in:st=0:d={fade_in},fade=t=out:st={fade_out_start}:d={fade_out}",
            '-c:a', 'copy',
            str(output_file)
        ]
        
        print(f"Adding fade effects to {input_path.name}...")
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Video with fade effects saved to: {output_file}")
        
        return str(output_file)
    
    def get_video_info(self, input_file: str) -> dict:
        """
        Get video information
        
        Args:
            input_file: Input video file path
            
        Returns:
            Dictionary with video information
        """
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration,size:stream=width,height,codec_name',
            '-of', 'json',
            str(input_file)
        ]
        
        result = subprocess.check_output(cmd).decode()
        import json
        return json.loads(result)


def main():
    """Example usage"""
    processor = VideoProcessor("./recordings")
    
    # List recordings
    recordings = processor.list_recordings()
    print(f"Found {len(recordings)} recordings:")
    for video in recordings:
        print(f"  - {video.name}")
    
    # Example: Convert first recording to MP4
    if recordings:
        processor.convert_to_mp4(str(recordings[0]), quality='high')


if __name__ == "__main__":
    main()
