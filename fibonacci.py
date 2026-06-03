"""
This script calculates and prints the first 10 numbers of the Fibonacci sequence.
"""

def generate_fibonacci(count):
    """
    Generates the first `count` numbers of the Fibonacci sequence.
    """
    fib_list = []
    a, b = 0, 1
    for _ in range(count):
        fib_list.append(a)
        a, b = b, a + b
    return fib_list

if __name__ == "__main__":
    num_terms = 10
    fib_sequence = generate_fibonacci(num_terms)
    print(f"The first {num_terms} numbers of the Fibonacci sequence are:")
    print(fib_sequence)
