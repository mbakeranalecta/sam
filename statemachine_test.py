from statemachine import StateMachine

def ones_counter(val):
    print("ONES State:    ", end=' ')
    while 1:
        if val <= 0 or val >= 30:
           newState = "Out_of_Range"
           break
        elif 20 <= val < 30:
            newState = "TWENTIES"
            break
        elif 10 <= val < 20:
            newState = "TENS"
            break
        else:
            print("  @ %2.1f+" % val, end=' ')
        val = math_func(val)
    print("  >>")
    return newState, val

def tens_counter(val):
    print("TENS State:    ", end=' ')
    while 1:
        if val <= 0 or val >= 30:
           newState = "Out_of_Range"
           break
        elif 1 <= val < 10:
            newState = "ONES"
            break
        elif 20 <= val < 30:
            newState = "TWENTIES"
            break
        else:
            print("  #%2.1f+" % val, end=' ')
        val = math_func(val)
    print("  >>")
    return (newState, val)

def twenties_counter(val):
    print("TWENTIES State:", end=' ')
    while 1:
        if val <= 0 or val >= 30:
           newState = "Out_of_Range"
           break
        elif 1 <= val < 10:
            newState = "ONES"
            break
        elif 10 <= val < 20:
            newState = "TENS"
            break
        else:
            print("  *%2.1f+" % val, end=' ')
        val = math_func(val)
    print("  >>")
    return (newState, val)

def math_func(n):
    from math import sin
    return abs(sin(n))*31

if __name__== "__main__":
    m = StateMachine()
    m.add_state("ONES", ones_counter)
    m.add_state("TENS", tens_counter)
    m.add_state("TWENTIES", twenties_counter)
    m.add_state("OUT_OF_RANGE", None, end_state=1)
    m.set_start("ONES")
    m.run(1)

