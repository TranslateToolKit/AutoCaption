#!/usr/bin/env python
from __future__ import absolute_import, print_function, unicode_literals
import argparse
import audioop
#from googleapiclient.discovery import build
import json
import math
import multiprocessing
import os
import requests
import subprocess
import sys
import tempfile
import wave
import speech_recognition as sr
r = sr.Recognizer()

from progressbar import ProgressBar, Percentage, Bar, ETA

from autocaption.constants import (
    LANGUAGE_CODES, 
)
from autocaption.formatters import FORMATTERS

DEFAULT_SUBTITLE_FORMAT = 'srt'
DEFAULT_CONCURRENCY = 10
DEFAULT_SRC_LANGUAGE = 'en'
DEFAULT_DST_LANGUAGE = 'en'


def percentile(arr, percent):
    arr = sorted(arr)
    k = (len(arr) - 1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c: return arr[int(k)]
    d0 = arr[int(f)] * (c - k)
    d1 = arr[int(c)] * (k - f)
    return d0 + d1


def is_same_language(lang1, lang2):
    return lang1.split("-")[0] == lang2.split("-")[0]


class FLACConverter(object):
    def __init__(self, source_path, include_before=0.25, include_after=0.25):
        self.source_path = source_path
        self.include_before = include_before
        self.include_after = include_after

    def __call__(self, region):        
        try:
            start, end = region
            start = max(0, start - self.include_before)
            end += self.include_after
            temp = tempfile.NamedTemporaryFile(suffix='.flac', dir=os.path.dirname(self.source_path), delete=False)
            command = ["ffmpeg","-ss", str(start), "-t", str(end - start),
                       "-y", "-i", self.source_path,
                       "-loglevel", "error", temp.name]
            use_shell = True if os.name == "nt" else False
            subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
            return temp.name#temp.read()

        except KeyboardInterrupt:
            return


class SpeechRecognizer(object):
    def __init__(self, language="en", rate=44100, retries=3, engine="recognize_sphinx"):
        self.language = language
        self.rate = rate
        self.engine = engine
        self.retries = retries

    def __call__(self, file):
        #print(file)
        try:
            for i in range(self.retries):
                with sr.AudioFile(file) as source:
                    audio = r.record(source)
                try:    
                    line = ""
                    if self.engine == "recognize_sphinx":                
                        line = r.recognize_sphinx(audio)
                    elif self.engine == "recognize_google":
                        line = r.recognize_google(audio)
                    elif self.engine == "recognize_wit":
                        line = r.recognize_wit(audio)
                    elif self.engine == "recognize_bing":
                        line = r.recognize_bing(audio)
                    elif self.engine == "recognize_api":
                        line = r.recognize_api(audio)
                    elif self.engine == "recognize_houndify":
                        line = r.recognize_houndify(audio)
                    elif self.engine == "recognize_ibm":
                        line = r.recognize_ibm(audio)
                    else :
                        pass
                    #print("Sphinx thinks you said" + line)
                    return line
                except sr.UnknownValueError:
                    print("can not understand")
                except sr.RequestError as e:
                    print("error")
                '''
                url = GOOGLE_SPEECH_API_URL.format(lang=self.language, key=self.api_key)
                headers = {"Content-Type": "audio/x-flac; rate=%d" % self.rate}

                try:
                    resp = requests.post(url, data=data, headers=headers)
                except requests.exceptions.ConnectionError:
                    continue

                for line in resp.content.decode().split("\n"):
                    try:
                        line = json.loads(line)
                        line = line['result'][0]['alternative'][0]['transcript']
                        return line[:1].upper() + line[1:]
                    except:
                        # no result
                        continue
                '''
        except KeyboardInterrupt:
            return

class Translator(object):
    def __init__(self, language, api_key, src, dst):
        self.language = language
        self.api_key = api_key
        self.service = build('translate', 'v2',
                             developerKey=self.api_key)
        self.src = src
        self.dst = dst

    def __call__(self, sentence):
        try:
            if not sentence: return
            result = self.service.translations().list(
                source=self.src,
                target=self.dst,
                q=[sentence]
            ).execute()
            if 'translations' in result and len(result['translations']) and \
                'translatedText' in result['translations'][0]:
                return result['translations'][0]['translatedText']
            return ""

        except KeyboardInterrupt:
            return


def which(program):
    def is_exe(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program + '.exe')
            if is_exe(exe_file):
                return exe_file
    return None


def extract_audio(filename, tempdir,channels=1, rate=16000):
    temp = tempfile.NamedTemporaryFile(suffix='.wav', dir=tempdir, delete=False)
    print(temp.name)
    if not os.path.isfile(filename):
        print("The given file does not exist: {0}".format(filename))
        raise Exception("Invalid filepath: {0}".format(filename))
    if not which("ffmpeg"):
        print("ffmpeg: Executable not found on machine.")
        raise Exception("Dependency not found: ffmpeg")
    command = ["ffmpeg", "-y", "-i", filename, "-ac", str(channels), "-ar", str(rate), "-loglevel", "error", temp.name]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
    return temp.name, rate


def find_speech_regions(filename, frame_width=4096, min_region_size=0.5, max_region_size=6):
    reader = wave.open(filename)
    sample_width = reader.getsampwidth()
    rate = reader.getframerate()
    n_channels = reader.getnchannels()
    chunk_duration = float(frame_width) / rate

    n_chunks = int(math.ceil(reader.getnframes()*1.0 / frame_width))
    energies = []

    for i in range(n_chunks):
        chunk = reader.readframes(frame_width)
        energies.append(audioop.rms(chunk, sample_width * n_channels))

    threshold = percentile(energies, 0.2)

    elapsed_time = 0

    regions = []
    region_start = None

    for energy in energies:
        is_silence = energy <= threshold
        max_exceeded = region_start and elapsed_time - region_start >= max_region_size

        if (max_exceeded or is_silence) and region_start:
            if elapsed_time - region_start >= min_region_size:
                regions.append((region_start, elapsed_time))
                region_start = None

        elif (not region_start) and (not is_silence):
            region_start = elapsed_time
        elapsed_time += chunk_duration
    return regions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_path', help="Path to the video or audio file to subtitle", nargs='?')
    parser.add_argument('-C', '--concurrency', help="Number of concurrent API requests to make",
                        type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument('-o', '--output',
                        help="Output path for subtitles (by default, subtitles are saved in \
                        the same directory and name as the source path)")
    parser.add_argument('-F', '--format', help="Destination subtitle format",
                        default=DEFAULT_SUBTITLE_FORMAT)
    parser.add_argument('-S', '--src-language', help="Language spoken in source file",
                        default=DEFAULT_SRC_LANGUAGE)
    parser.add_argument('-D', '--dst-language', help="Desired language for the subtitles",
                        default=DEFAULT_DST_LANGUAGE)
    parser.add_argument('-K', '--api-key',
                        help="The Google Translate API key to be used. (Required for subtitle translation)")
    parser.add_argument('--list-formats', help="List all available subtitle formats", action='store_true')
    parser.add_argument('--list-languages', help="List all available source/destination languages", action='store_true')

    args = parser.parse_args()

    if args.list_formats:
        print("List of formats:")
        for subtitle_format in FORMATTERS.keys():
            print("{format}".format(format=subtitle_format))
        return 0

    if args.list_languages:
        print("List of all languages:")
        for code, language in sorted(LANGUAGE_CODES.items()):
            print("{code}\t{language}".format(code=code, language=language))
        return 0

    if args.format not in FORMATTERS.keys():
        print(
            "Subtitle format not supported. "
            "Run with --list-formats to see all supported formats."
        )
        return 1

    if args.src_language not in LANGUAGE_CODES.keys():
        print(
            "Source language not supported. "
            "Run with --list-languages to see all supported languages."
        )
        return 1

    if args.dst_language not in LANGUAGE_CODES.keys():
        print(
            "Destination language not supported. "
            "Run with --list-languages to see all supported languages."
        )
        return 1

    if not args.source_path:
        print("Error: You need to specify a source path.")
        return 1

    try:
        base = os.path.dirname(args.source_path)
        print(base)
        tempdir = tempfile.mkdtemp(suffix="",prefix="",dir=base)
        print(tempdir)
        subtitle_file_path = generate_subtitles(
            source_path=args.source_path,
            temp_path=tempdir,
            concurrency=args.concurrency,
            src_language=args.src_language,
            dst_language=args.dst_language,
            api_key=args.api_key,
            subtitle_file_format=args.format,
            output=args.output,
        )
        print("Subtitles file created at {}".format(subtitle_file_path))
    except KeyboardInterrupt:
        return 1

    return 0


def generate_subtitles(
    source_path,
    temp_path,
    output=None,
    concurrency=DEFAULT_CONCURRENCY,
    src_language=DEFAULT_SRC_LANGUAGE,
    dst_language=DEFAULT_DST_LANGUAGE,
    subtitle_file_format=DEFAULT_SUBTITLE_FORMAT,
    api_key=None,
):
    audio_filename, audio_rate = extract_audio(source_path,temp_path)

    regions = find_speech_regions(audio_filename)
    print(regions)
    pool = multiprocessing.Pool(concurrency)
    converter = FLACConverter(source_path=audio_filename)
    recognizer = SpeechRecognizer(language=src_language, rate=audio_rate)

    transcripts = []
    if regions:
        try:
            widgets = ["Converting speech regions to FLAC files: ", Percentage(), ' ', Bar(), ' ',
                       ETA()]
            pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
            extracted_regions = []
            for i, extracted_region in enumerate(pool.imap(converter, regions)):
                extracted_regions.append(extracted_region)
                pbar.update(i)
            pbar.finish()

            widgets = ["Performing speech recognition: ", Percentage(), ' ', Bar(), ' ', ETA()]
            pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()

            for i, transcript in enumerate(pool.imap(recognizer, extracted_regions)):
                transcripts.append(transcript)
                pbar.update(i)
            pbar.finish()

            if not is_same_language(src_language, dst_language):
                if api_key:
                    google_translate_api_key = api_key
                    translator = Translator(dst_language, google_translate_api_key,
                                            dst=dst_language,
                                            src=src_language)
                    prompt = "Translating from {0} to {1}: ".format(src_language, dst_language)
                    widgets = [prompt, Percentage(), ' ', Bar(), ' ', ETA()]
                    pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
                    translated_transcripts = []
                    for i, transcript in enumerate(pool.imap(translator, transcripts)):
                        translated_transcripts.append(transcript)
                        pbar.update(i)
                    pbar.finish()
                    transcripts = translated_transcripts
                else:
                    print(
                        "Error: Subtitle translation requires specified Google Translate API key. "
                        "See --help for further information."
                    )
                    return 1

        except KeyboardInterrupt:
            pbar.finish()
            pool.terminate()
            pool.join()
            print("Cancelling transcription")
            raise

    timed_subtitles = [(r, t) for r, t in zip(regions, transcripts) if t]
    formatter = FORMATTERS.get(subtitle_file_format)
    formatted_subtitles = formatter(timed_subtitles)

    dest = output

    if not dest:
        base, ext = os.path.splitext(source_path)
        dest = "{base}.{format}".format(base=base, format=subtitle_file_format)

    with open(dest, 'wb') as f:
        f.write(formatted_subtitles.encode("utf-8"))

    #os.remove(audio_filename)

    return dest

if __name__ == '__main__':
    sys.exit(main())
