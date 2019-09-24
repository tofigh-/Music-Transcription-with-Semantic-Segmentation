
import h5py
import pretty_midi
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from librosa import note_to_midi
from project.Evaluate.eval_utils import roll_down_sample, find_occur

def plot3(pred):
    fig, axes = plt.subplots(nrows=2)
    
    th = 0.5
    
    on = pred[:,:,1]
    on = (on-np.mean(on))/np.std(on)
    #on_th = np.where(on>2.5, 1, 0)
    on[on<th] = 0
    on = roll_down_sample(on)
    axes[0].imshow(on.transpose(), origin="lower", aspect="auto")
    
    on = pred[:,:,2]
    on = (on-np.mean(on))/np.std(on)
    #on_th = np.where(on>5, 1, 0)
    on[on<th] = 0
    on = roll_down_sample(on)
    axes[1].imshow(on.transpose(), origin="lower", aspect="auto")
    
    """
    on = pred[:,:,3]
    on = (on-np.mean(on))/np.std(on)
    #axes[2].imshow(on.transpose(), origin="lower", aspect="auto")
    #on_th = np.where(on>10, 1, 0)
    on[on<th] = 0
    on = roll_down_sample(on)
    axes[2].imshow(on.transpose(), origin="lower", aspect="auto")
    """
    plt.show()
    
def draw_roll(mm):
    roll = mm.get_piano_roll(fs=50)
    roll = np.where(roll>0, 1, 0)
    plt.imshow(roll, aspect="auto", origin="lower")
    
    plt.show()

def infer_pitch(pitch):
    """
        Dim: time x 4 (off, dura, onset, offset)
    """
    
    # Threshold parameters for note finding
    ws = 16 # window size, ws*0.02sec
    bound = 2 # peak value detection for onset and offset, the more center, the more strict (value between 0~ws-1)
    occur_th = ws-2 # register
    shortest = 5 # shortest note duration
    offset_vs_dura = 2 # register a new note according to either offset(bigger val) or duration(smaller val) event

    pitch = np.insert(pitch, 0, np.zeros((ws, pitch.shape[1])), axis=0) # padding before the pitch occurence
    onset = []
    notes = []
    
    def register_note(on, end_t, kmsgs):
        # register one note
        if end_t-on >= shortest:
            nn = {"start": on-ws, "end": end_t-ws, **kmsgs}
            notes.append(nn)
        
        del onset[0]
    
    for i in range(len(pitch)):
        window = pitch[i:i+ws]
        w_on = window[:,2]
        w_off = window[:,1] + window[:,2] #+ window[:,3] # onset + duration + offset
        
        if (w_on.argmax() == bound) and np.max(w_on)>0:
            # register onset occurence
            if len(onset)>0:
                # close previous onset and register a new note first
                register_note(onset[0], i+bound, {"added": "onset", "stren": pitch[onset[0], 2]})
                #nn = {"start": onset[0], "end": i+bound-1, "added": "onset"}
                #notes.append(nn)
                #del onset[0]
            
            onset.append(i)
            continue
            
        if len(onset)==0:
            continue
        if np.sum(w_off[:occur_th]) > 0 and np.sum(w_off[occur_th:]) <= 0:
            register_note(onset[0], i+occur_th, {"added": "off_silence", "stren": pitch[onset[0], 2]})
    
    return notes
  
def infer_piece(piece):
    """
        Dim: time x 88 x 4 (off, dura, onset, offset)
    """
    assert(piece.shape[1] == 88), "Please down sample the pitch to 88 first (current: {}).format(piece.shape[1])"
    t_unit = 0.02 # constant, do not modify
    min_align_diff = 1 # to align the onset between notes with a short time difference 
    
    notes = []
    for i in range(88):
        print("Pitch: {}/{}".format(i+1, 88), end="\r")
        
        pitch = piece[:,i]
        if np.sum(pitch) <= 0:
            continue
            
        pns = infer_pitch(pitch)
        for ns in pns:
            ns["pitch"] = i
            notes.append(ns)
            
    notes = sorted(notes, key=lambda d: d["start"])
    last_start = 0
    for i in range(len(notes)):
        start_diff = notes[i]["start"] - last_start 
        if start_diff < min_align_diff:
            notes[i]["start"] -= start_diff
            notes[i]["end"] -= start_diff
        else:
            last_start = notes[i]["start"]
            
    return notes
    
def find_min_max_stren(notes):
    MIN = 999
    MAX = 0
    for nn in notes:
        nn_s = nn["stren"]
        if nn_s > MAX:
            MAX = nn_s
        if nn_s < MIN:
            MIN = nn_s
    
    return MIN, MAX

def to_midi(notes, t_unit=0.02):
    midi = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0)
    
    
    l, u = find_min_max_stren(notes)
    s_low = 60
    s_up = 127
    v_map = lambda stren: int(s_low+((s_up-s_low)*((stren-l)/(u-l+0.0001))))
    
    low_b = note_to_midi("A0")
    coll = set()
    for nn in notes:
        pitch = nn["pitch"] + low_b
        start = nn["start"] * t_unit
        end = nn["end"] * t_unit
        volume = v_map(nn["stren"])
        coll.add(pitch)
        m_note = pretty_midi.Note(velocity=volume, pitch=pitch, start=start, end=end)
        piano.notes.append(m_note)
    midi.instruments.append(piano)
    return midi

def down_sample(pred):
    dd = roll_down_sample(pred[:,:,0])
    for i in range(1, pred.shape[2]):
        dd = np.dstack([dd, roll_down_sample(pred[:,:,i], occur_num=2)])

    return dd

def PostProcess(pred, mode="note", onset_th=5, dura_th=2, frm_th=1, t_unit=0.02):
    if mode == "note":
        onset = pred[:,:,2]
        dura = pred[:,:,1]
        
        onset = np.where(onset<dura, 0, onset)
        
        # Normalize along each channel and filter by the nomalized value
        # onset channel
        onset = (onset-np.mean(onset))/np.std(onset)
        onset = np.where(onset<onset_th, 0, onset)
        pred[:,:,2] = onset
        
        # duration channel
        dura = (dura-np.mean(dura))/np.std(dura)
        dura = np.where(dura<dura_th, 0, dura)
        pred[:,:,1] = dura
        
        notes = infer_piece(down_sample(pred))
        midi = to_midi(notes, t_unit=t_unit)
    
    elif mode == "frame":
        ch_num = pred.shape[2]
        if ch_num == 2:
            mix = pred[:,:,1]
        elif ch_num == 3:
            mix = pred[:,:,1] + pred[:,:,2]
        else:
            raise ValueError("Unknown channel length: {}".format(ch_num))
        
        p = (mix-np.mean(mix))/np.std(mix)
        p = np.where(p>frm_th, 1, 0)
        p = roll_down_sample(p)
        
        notes = []
        for idx in range(p.shape[1]):
            _, onset_interval = find_occur(p[:,idx], t_unit=t_unit)
            _, offset_interval = find_occur(p[:,idx], mode="offset", t_unit=t_unit)
            if len(onset_interval) != len(offset_interval):
                print("WRNING: length of onset and offset not consistent. Onset len: {}, offset len: {}.".format(len(onset_interval), len(offset_interval)))
                min_len = min(len(onset_interval), len(offset_interval))
                onset_interval = onset_interval[:min_len]
                offset_interval = offset_interval[:min_len]

            for i in range(len(onset_interval)):
                note = {}
                onset = onset_interval[i][0]
                offset = offset_interval[i][0]
                note["pitch"] = idx
                note["start"] = int(round(onset/t_unit))
                note["end"] = int(round(offset/t_unit))
                note["stren"] = mix[note["start"], idx*4]
                notes.append(note)
        midi = to_midi(notes, t_unit=t_unit)
    else:
        raise ValueError("Supported mode are ['note', 'frame']. Given mode: {}".format(mode))

    return midi
        
        
if __name__ == "__main__":
    f_name = "Maestro-Attn-W4.2_predictions.hdf"
    p_in = h5py.File(f_name, "r")
    pred = p_in["0"][:]
    p_in.close()
    
    pp = pred#[16744:22000]
    midi = PostProcess(pp, mode="frame")
    midi.write("test.mid")
    
    draw_roll(midi)   
    plot3(pp)
        
        
        
