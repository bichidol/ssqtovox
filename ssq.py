import struct
import os

TICKS_PER_BEAT = 48
BEATS_PER_MEASURE = 4
TICKS_PER_MEASURE = 4096

ARROW_CATEGORIES = {
    "Player 1 Left": "#TRACK3",
    "Player 1 Down": "#TRACK4",
    "Player 1 Up": "#TRACK5",
    "Player 1 Right": "#TRACK6",
}

def read_chunk_header(file):
    header_struct = struct.Struct('<I2H2H')
    data = file.read(header_struct.size)
    if data and len(data) == header_struct.size:
        return header_struct.unpack(data)
    return None

def parse_tempo_changes_corrected(chunk):
    time_offsets = []
    tempo_data = []
    for i in range(chunk['param3']):
        time_offsets.append(struct.unpack('<I', chunk['data'][i*4:i*4+4])[0])
    offset = chunk['param3'] * 4
    for i in range(chunk['param3']):
        tempo_data.append(struct.unpack('<I', chunk['data'][offset+i*4:offset+i*4+4])[0])

    bpm_changes = []
    for i in range(1, len(time_offsets)):
        delta_offset = time_offsets[i] - time_offsets[i-1]
        delta_ticks = tempo_data[i] - tempo_data[i-1]
        ticks_per_second = chunk['param2']
        measure_length = 4096
        bpm = (delta_offset / measure_length) / ((delta_ticks / ticks_per_second) / 240)
        bpm_changes.append(bpm)
    
    return time_offsets, bpm_changes

def parse_steps_corrected(chunk):
    time_offsets = []
    step_data = []
    for i in range(chunk['param3']):
        time_offsets.append(struct.unpack('<I', chunk['data'][i*4:i*4+4])[0])
    offset = chunk['param3'] * 4
    for i in range(chunk['param3']):
        step_data.append(struct.unpack('<B', chunk['data'][offset+i:offset+i+1])[0])

    extra_data_offset = offset + len(step_data)
    if extra_data_offset % 2 != 0: 
        extra_data_offset += 1

    freeze_lengths = [0] * len(step_data)
    for i in range(len(step_data) - 1):
        if step_data[i] != 0x00 and (i == len(step_data) - 1 or step_data[i + 1] == 0x00):
            start_mbt = offset_to_mbt_corrected(time_offsets[i])
            end_mbt = offset_to_mbt_corrected(time_offsets[i + 1])
            freeze_lengths[i] = mbt_to_ticks(end_mbt) - mbt_to_ticks(start_mbt)
        elif step_data[i] == 0x00:
            panel_byte, type_byte = struct.unpack('<BB', chunk['data'][extra_data_offset:extra_data_offset+2])
            extra_data_offset += 2
            if type_byte == 0x01:
                step_data[i] = (0x00, panel_byte)

    print(time_offsets)
    print(step_data)
    print(freeze_lengths)
    return time_offsets, step_data, freeze_lengths


def byte_to_arrows_corrected(byte_val):
    arrows = []
    bit_to_arrow = {
        1: "Player 1 Left",
        2: "Player 1 Down",
        4: "Player 1 Up",
        8: "Player 1 Right"
    }
    if isinstance(byte_val, tuple):
        freeze_val = byte_val[1]
        arrows.append(bit_to_arrow[freeze_val])
        arrows.append("Freeze")
        return arrows
    
    for val, arrow in bit_to_arrow.items():
        if byte_val & val:
            arrows.append(arrow)
    return arrows


def mbt_to_ticks(mbt):
    measures, beats, ticks = map(int, mbt.split(','))
    return (measures - 1) * 192 + (beats - 1) * TICKS_PER_BEAT + ticks

def offset_to_mbt_corrected(offset):
    
    measure_float = offset / TICKS_PER_MEASURE
    measure = int(measure_float)
    beat_float = (measure_float - measure) * BEATS_PER_MEASURE
    beat = int(beat_float)
    tick = round((beat_float - beat) * TICKS_PER_BEAT)

    measure += 1
    beat += 1

    return f"{measure:03},{beat:02},{tick:02}"

def write_step_data_to_file(file, step_data):
    categorized_data = {category: [] for category in ARROW_CATEGORIES.keys()}
    
    i = 0
    while i < len(step_data):
        offset, arrows, length = step_data[i]
        
        # Case: Two arrows followed by two different freeze lengths in two freeze sets
        if (len(arrows) == 2 and 
            i+1 < len(step_data) and 'Freeze' in step_data[i+1][1] and 
            i+2 < len(step_data) and 'Freeze' in step_data[i+2][1] and 
            step_data[i+1][0] != step_data[i+2][0]):
            
            freeze_arrow_1 = step_data[i+1][1][0]
            freeze_arrow_2 = step_data[i+2][1][0]

            freeze_offset_1 = step_data[i+1][0]
            freeze_offset_2 = step_data[i+2][0]

            mbt_start = offset_to_mbt_corrected(offset)
            mbt_freeze_1 = offset_to_mbt_corrected(freeze_offset_1)
            mbt_freeze_2 = offset_to_mbt_corrected(freeze_offset_2)

            length_freeze_1 = mbt_to_ticks(mbt_freeze_1) - mbt_to_ticks(mbt_start)
            length_freeze_2 = mbt_to_ticks(mbt_freeze_2) - mbt_to_ticks(mbt_start)

            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                if arrow == freeze_arrow_1:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_freeze_1}\t0")
                elif arrow == freeze_arrow_2:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_freeze_2}\t0")
                else:
                    categorized_data[arrow].append(f"{mbt_format}\t0\t0")
            
            i += 3  
            continue

        
        # Case: Two arrows followed by the same freeze length for both freeze sets
        elif (len(arrows) == 2 and 
            i+1 < len(step_data) and 'Freeze' in step_data[i+1][1] and 
            i+2 < len(step_data) and 'Freeze' in step_data[i+2][1] and 
            step_data[i+1][0] == step_data[i+2][0]):
            
            for arrow in arrows:
                if arrow != 'Freeze':
                    mbt_format = offset_to_mbt_corrected(offset)
                    categorized_data[arrow].append(f"{mbt_format}\t{length}\t0")
            
            i += 3  
            continue

        # Case: Two arrows followed by the same freeze length in a empty set and a freeze set
        elif (len(arrows) == 2 and 
              i+1 < len(step_data) and 'Freeze' in step_data[i+1][1] and 
              i+2 < len(step_data) and not step_data[i+2][1] and 
              step_data[i+1][0] == step_data[i+2][0]):
            
            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                categorized_data[arrow].append(f"{mbt_format}\t{length}\t0")
            
            i += 3  
            continue
        
        # Case: Two arrows followed by two empty sets that are the same
        elif (len(arrows) == 2 and 
            i+1 < len(step_data) and not step_data[i+1][1] and 
            i+2 < len(step_data) and not step_data[i+2][1] and 
            step_data[i+1][0] == step_data[i+2][0]):
            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                categorized_data[arrow].append(f"{mbt_format}\t{length}\t0")
            i += 3
            continue

        # Case: Two arrows followed by two different empty sets
        elif (len(arrows) == 2 and 
            i+1 < len(step_data) and not step_data[i+1][1] and 
            i+2 < len(step_data) and not step_data[i+2][1] and 
            step_data[i+1][0] != step_data[i+2][0]):
            
            empty_offset_1 = step_data[i+1][0]
            empty_offset_2 = step_data[i+2][0]

            mbt_start = offset_to_mbt_corrected(offset)
            mbt_empty_1 = offset_to_mbt_corrected(empty_offset_1)
            mbt_empty_2 = offset_to_mbt_corrected(empty_offset_2)

            length_empty_1 = mbt_to_ticks(mbt_empty_1) - mbt_to_ticks(mbt_start)
            length_empty_2 = mbt_to_ticks(mbt_empty_2) - mbt_to_ticks(mbt_start)

            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                if arrow == freeze_arrow_1:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_empty_1}\t0")
                elif arrow == freeze_arrow_2:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_empty_2}\t0")
                else:
                    categorized_data[arrow].append(f"{mbt_format}\t0\t0")
            i += 3
            continue


        # Case: Two arrows followed by one freeze and one different empty set
        elif (len(arrows) == 2 and 
            i+1 < len(step_data) and 'Freeze' in step_data[i+1][1] and 
            i+2 < len(step_data) and not step_data[i+2][1] and 
            step_data[i+1][0] != step_data[i+2][0]):
            
            freeze_arrow = step_data[i+1][1][0]
            freeze_offset = step_data[i+1][0]
            empty_offset = step_data[i+2][0]

            mbt_start = offset_to_mbt_corrected(offset)
            mbt_freeze = offset_to_mbt_corrected(freeze_offset)
            mbt_empty = offset_to_mbt_corrected(empty_offset)

            length_freeze = mbt_to_ticks(mbt_freeze) - mbt_to_ticks(mbt_start)
            length_empty = mbt_to_ticks(mbt_empty) - mbt_to_ticks(mbt_start)

            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                if arrow == freeze_arrow:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_freeze}\t0")
                else:
                    categorized_data[arrow].append(f"{mbt_format}\t{length_empty}\t0")
            i += 3
            continue

        # 2 arrows followed by 1 freeze set
        elif (len(arrows) == 2 and i+1 < len(step_data) and 'Freeze' in step_data[i+1][1]):
            freeze_arrow = step_data[i+1][1][0]  
            for arrow in arrows:
                mbt_format = offset_to_mbt_corrected(offset)
                if arrow == freeze_arrow:
                    categorized_data[arrow].append(f"{mbt_format}\t{length}\t0")
                else:
                    categorized_data[arrow].append(f"{mbt_format}\t0\t0")
            i += 2 
            continue

        #one arrow followed by a freeze set
        elif len(arrows) == 1 and i+1 < len(step_data) and 'Freeze' in step_data[i+1][1]:
            if arrows[0] != 'Freeze':
                mbt_format = offset_to_mbt_corrected(offset)
                categorized_data[arrows[0]].append(f"{mbt_format}\t{length}\t0")
            i += 2 
            continue

        # Case: One arrow followed by an empty set
        elif (len(arrows) == 1 and 
            i+1 < len(step_data) and not step_data[i+1][1]):
            
            arrow = arrows[0]
            empty_offset = step_data[i+1][0]

            mbt_start = offset_to_mbt_corrected(offset)
            mbt_empty = offset_to_mbt_corrected(empty_offset)

            length_empty = mbt_to_ticks(mbt_empty) - mbt_to_ticks(mbt_start)

            mbt_format = offset_to_mbt_corrected(offset)
            categorized_data[arrow].append(f"{mbt_format}\t{length_empty}\t0")

            i += 2
            continue

        #else
        else:
            for arrow in arrows:
                if arrow != 'Freeze':
                    mbt_format = offset_to_mbt_corrected(offset)
                    categorized_data[arrow].append(f"{mbt_format}\t0\t0")
            i += 1
        
    first_category_written = False
    for arrow, category in ARROW_CATEGORIES.items():
        if categorized_data[arrow]:
            if first_category_written: 
                file.write("//====================================\n\n")
            else:
                first_category_written = True

            file.write(category + "\n")
            for line in categorized_data[arrow]:
                file.write(line + "\n")
            file.write("#END\n\n")

def calculate_end_position(step_data):
    highest_offset = max([data[0] for data in step_data])
    mbt_format = offset_to_mbt_corrected(highest_offset)
    measures, beats, ticks = map(int, mbt_format.split(','))
    measures += 3
    return f"{measures:03},01,00"

def adjust_bpm_values(bpm_changes):
    if bpm_changes and bpm_changes[0] <= 0:
        bpm_changes[0] = bpm_changes[1]
    return bpm_changes

def main():
    filepath = input("path to file: ")
    
    chunks = []
    with open(filepath, 'rb') as file:
        header = read_chunk_header(file)
        while header and header[0] != 0:
            length, param1, param2, param3, param4 = header
            data = file.read(length - 12)
            chunks.append({
                'length': length,
                'param1': param1,
                'param2': param2,
                'param3': param3,
                'param4': param4,
                'data': data
            })
            if length % 4 != 0:
                padding = 4 - (length % 4)
                file.read(padding)
            header = read_chunk_header(file)

    chart_type = input("chart to extract (e.g., 'csp', 'esp'): ")
    
    chart_map = {
        "csp": 0x0614,
        "esp": 0x0314,
        "dsp": 0x0214,
        "bsp": 0x0114,
    }
    
    bpm_offsets, bpm_changes = parse_tempo_changes_corrected(next(chunk for chunk in chunks if chunk['param1'] == 1))
    bpm_changes = adjust_bpm_values(bpm_changes)
    step_offsets, step_values, freeze_lengths = parse_steps_corrected(next(chunk for chunk in chunks if chunk['param1'] == 3 and chunk['param2'] == chart_map[chart_type]))

    step_arrows = [byte_to_arrows_corrected(byte_val) for byte_val in step_values]

    step_data = list(zip(step_offsets, step_arrows, freeze_lengths))

    output_filename = os.path.basename(filepath).split('.')[0] + '-' + chart_type + '.vox'
    with open(output_filename, 'w') as file:
        file.write("//====================================\n")
        file.write("// SOUND VOLTEX OUTPUT TEXT FILE\n")
        file.write("//====================================\n\n")

        file.write("#FORMAT VERSION\n")
        file.write("10\n")
        file.write("#END\n\n")

        file.write("#BEAT INFO\n")
        file.write("001,01,00\t4\t4\n")
        file.write("#END\n\n")

        file.write("#BPM INFO\n")
        for offset, bpm in zip(bpm_offsets, bpm_changes):
            mbt_format = offset_to_mbt_corrected(offset)
            file.write(f"{mbt_format}\t{bpm:8.4f}\t4\n")
        file.write("#END\n\n")

        file.write("#TILT MODE INFO\n")
        file.write("001,01,00\t0\n")
        file.write("#END\n\n")

        file.write("#LYRIC INFO\n")
        file.write("#END\n\n")

        end_position = calculate_end_position(step_data)
        file.write("#END POSITION\n")
        file.write(f"{end_position}\n")
        file.write("#END\n\n")

        file.write("#TAB EFFECT INFO\n")
        file.write("#END\n\n")

        file.write("#FXBUTTON EFFECT INFO\n")
        file.write("#END\n\n")

        file.write("#TAB PARAM ASSIGN INFO\n")
        file.write("#END\n\n")

        file.write("#REVERB EFFECT PARAM\n")
        file.write("#END\n\n")

        file.write("//====================================\n")
        file.write("// TRACK INFO\n")
        file.write("//====================================\n\n")

        file.write("#TRACK1\n")
        file.write("#END\n\n")

        file.write("//====================================\n\n")

        file.write("#TRACK2\n")
        file.write("#END\n\n")

        file.write("//====================================\n\n")

        write_step_data_to_file(file, step_data)

        file.write("//====================================\n\n")

        file.write("#TRACK7\n")
        file.write("#END\n\n")

        file.write("//====================================\n\n")

        file.write("#TRACK8\n")
        file.write("#END\n\n")

        file.write("//====================================\n\n")

        file.write("//====================================\n")
        file.write("// SPCONTROLER INFO\n")
        file.write("//====================================\n\n")

        file.write("#SPCONTROLER\n")
        file.write("#END\n")

    print(f"Data written to {output_filename}.")

if __name__ == "__main__":
    main()
